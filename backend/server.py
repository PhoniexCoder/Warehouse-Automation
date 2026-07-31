import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

if "OPENCV_FFMPEG_CAPTURE_OPTIONS" not in os.environ:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|rw_timeout;5000000|timeout;5000000"

import asyncio
import json
import logging
import multiprocessing
import os
import re
import sys

multiprocessing.set_start_method("spawn", force=True)

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api import v1_router
from api.exceptions import general_exception_handler, validation_exception_handler
from cv_engine.database import create_tables
from cv_engine.orchestration.camera_manager import CameraManager
from cv_engine.orchestration.frame_store import FrameStore
from cv_engine.orchestration.stream_manager import StreamManager
from fastapi.exceptions import RequestValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

LOGGER = logging.getLogger("server")

camera_manager = CameraManager()
frame_store = FrameStore()
stream_manager = StreamManager(frame_store)

app = FastAPI(title="Warehouse AI API", version="1.0.0")

_CV_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")
if not _CV_INTERNAL_KEY:
    raise RuntimeError("FATAL: INTERNAL_API_KEY env var must be set")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.include_router(v1_router, prefix="/api/v1")


import hashlib
import json
import re
import requests
import threading
import time

BUSINESS_BACKEND_URL = os.getenv("BUSINESS_BACKEND_URL", "http://localhost:8001")
MEDIA_DIR = os.getenv("MEDIA_DIR", "/app/media")

_DVRIP_URL_RE = re.compile(r"^dvrip://([^:]+):([^@]+)@([^:]+):(\d+)/(\d+)$")
_RTSP_URL_RE = re.compile(r"^rtsp://")


def _verify_cv_internal_key(x_internal_key: str = Header(..., alias="X-Internal-Key")) -> None:
    if x_internal_key != _CV_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


def _config_hash(config: dict) -> str:
    keys = {"model_path", "roi", "count_line", "source_type", "source", "detection_conf", "count_conf"}
    snapshot = {k: config.get(k) for k in sorted(keys)}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()


def _parse_dvrip_url(url: str) -> dict | None:
    """Parse dvrip://user:pass@host:port/channel into components."""
    m = _DVRIP_URL_RE.match(url)
    if not m:
        return None
    return {
        "username": m.group(1),
        "password": m.group(2),
        "host": m.group(3),
        "port": int(m.group(4)),
        "channel": int(m.group(5)),
    }


def _route_camera(cam_id: str, stream_url: str) -> bool:
    """Start the correct stream for a camera URL.

    dvrip:// URLs connect directly via DVRIP (CameraStream);
    native RTSP URLs are read directly (RtspCameraStream).
    file:// URLs and .mp4 files play local video (VideoFileCameraStream).
    go2rtc is not involved.
    Returns True if a stream was started.
    """
    if stream_url.startswith("dvrip://"):
        info = _parse_dvrip_url(stream_url)
        if not info:
            LOGGER.warning("VMS: Skipping unparseable DVRIP URL for %s: %s", cam_id, stream_url)
            return False
        stream_manager.start_camera(
            camera_id=cam_id,
            host=info["host"],
            port=info["port"],
            username=info["username"],
            password=info["password"],
            channel=info["channel"],
        )
        return True

    if stream_url.startswith("rtsp://"):
        stream_manager.start_camera_rtsp(camera_id=cam_id, rtsp_url=stream_url)
        return True

    # Local video file: file:///path/to/file.mp4 or bare filename.mp4
    if stream_url.startswith("file://") or stream_url.lower().endswith(".mp4"):
        # Strip file:// prefix
        file_name = stream_url[7:] if stream_url.startswith("file://") else stream_url
        # Resolve path: absolute paths used as-is; relative paths joined with MEDIA_DIR
        if os.path.isabs(file_name):
            file_path = file_name
        else:
            file_path = os.path.join(MEDIA_DIR, file_name)
        if not os.path.exists(file_path):
            LOGGER.warning("VMS: Video file not found for %s: %s", cam_id, file_path)
            return False
        stream_manager.start_camera_video(camera_id=cam_id, file_path=file_path)
        return True

    LOGGER.warning("VMS: Skipping camera %s with unsupported stream URL: %s", cam_id, stream_url)
    return False


def sync_cameras_loop():
    time.sleep(5)
    LOGGER.info("VMS Sync loop started (direct dvrip/rtsp mode)")
    while True:
        try:
            url = f"{BUSINESS_BACKEND_URL}/api/v1/cameras/internal/active"
            res = requests.get(url, timeout=5, headers={"X-Internal-Key": _CV_INTERNAL_KEY})
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    active_cameras = data["data"]
                    active_ids = set()

                    for cam in active_cameras:
                        try:
                            cam_id = cam["id"]
                            stream_url = cam.get("stream_url", "")
                            active_ids.add(cam_id)

                            if not stream_url:
                                continue

                            # Direct capture: DVRIP via CameraStream, RTSP via RtspCameraStream
                            if not _route_camera(cam_id, stream_url):
                                continue

                            # Start detection worker (reads from FrameStore)
                            config = {
                                "source_type": "file_store",
                                "line_y": 500,
                                "display_name": cam.get("camera_name", ""),
                                "target_fps": 5,
                                "model_path": cam.get("model_path") or "",
                                "roi": cam.get("roi"),
                                "count_line": cam.get("count_line"),
                                "detection_conf": 0.55,
                                "count_conf": 0.65,
                            }

                            if cam_id in camera_manager._configs:
                                old_hash = camera_manager._configs[cam_id].get("_hash", "")
                                new_hash = _config_hash(config)
                                config["_hash"] = new_hash

                                if new_hash != old_hash:
                                    LOGGER.info("VMS: Config changed for %s, restarting worker",
                                                 cam.get("camera_name"))
                                    camera_manager.stop_camera(cam_id)
                                    camera_manager.start_camera(cam_id, config)
                                else:
                                    health = camera_manager._health.get(cam_id, {})
                                    status = health.get("status", "")
                                    if status in ("dead", "stopped"):
                                        LOGGER.info("VMS: Retrying dead camera %s (%s)",
                                                     cam.get("camera_name"), cam_id)
                                        camera_manager.stop_camera(cam_id)
                                        camera_manager.start_camera(cam_id, config)
                            else:
                                config["_hash"] = _config_hash(config)
                                LOGGER.info("VMS: Starting camera worker for %s (%s) [direct->file_store]",
                                             cam.get("camera_name"), cam_id)
                                camera_manager.start_camera(cam_id, config)
                        except Exception:
                            LOGGER.exception("VMS: Failed to start camera %s", cam.get("id", "?"))

                    # Stop cameras that are no longer active
                    configured_ids = list(camera_manager._configs.keys())
                    for c_id in configured_ids:
                        if c_id not in active_ids:
                            LOGGER.info("VMS: Stopping camera worker for %s", c_id)
                            camera_manager.stop_camera(c_id)

                    # Stop streams for inactive cameras
                    stream_status = stream_manager.status
                    for s_cam_id in stream_status:
                        if s_cam_id not in active_ids:
                            LOGGER.info("VMS: Stopping stream for %s", s_cam_id)
                            stream_manager.stop_camera(s_cam_id)

        except Exception:
            LOGGER.exception("VMS: Sync loop error")
        time.sleep(10)


@app.on_event("startup")
def _startup() -> None:
    create_tables()
    LOGGER.info("Database tables ensured")

    camera_manager.start_all()
    LOGGER.info("CameraManager started")

    # Start VMS auto-sync thread
    sync_thread = threading.Thread(target=sync_cameras_loop, daemon=True, name="vms-sync")
    sync_thread.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    LOGGER.info("Shutting down StreamManager and CameraManager")
    stream_manager.stop_all()
    camera_manager.stop_all()


@app.get("/api/v1/cameras")
def get_cameras(x_internal_key: str = Header(..., alias="X-Internal-Key")) -> dict:
    if x_internal_key != _CV_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")
    return {
        "success": True,
        "data": camera_manager.get_status(),
        "stream_status": stream_manager.status,
        "error": None,
    }


@app.post("/api/v1/reset/{camera_id}")
def reset_camera_count(camera_id: str, x_internal_key: str = Header(..., alias="X-Internal-Key")) -> dict:
    """Reset a camera's detection/line counters (called by business backend)."""
    if x_internal_key != _CV_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")
    if not camera_manager.reset_camera(camera_id):
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return {
        "success": True,
        "data": {"camera_id": camera_id, "reset": True},
        "error": None,
    }


# ─── WebSocket Live Stream ──────────────────────────────────────────────

@app.websocket("/api/v1/stream/ws/{camera_id}")
async def ws_stream(websocket: WebSocket, camera_id: str):
    """WebSocket endpoint for live annotated JPEG frame streaming.

    Streams annotated JPEG frames (with YOLO bounding boxes & ROI overlay) from FrameStore.
    CameraWorker writes annotated frames; this endpoint reads them exclusively — no raw frame fallback.
    """
    api_key = websocket.query_params.get("key", "")
    if _CV_INTERNAL_KEY and api_key and api_key != _CV_INTERNAL_KEY:
        await websocket.close(code=4001, reason="Invalid API key")
        return

    # Check if stream or worker exists
    has_stream = stream_manager.get_stream(camera_id) is not None
    has_worker = camera_id in camera_manager._configs
    if not has_stream and not has_worker:
        for _ in range(30):
            await asyncio.sleep(0.5)
            if stream_manager.get_stream(camera_id) or camera_id in camera_manager._configs:
                has_stream = True
                break

    await websocket.accept()
    LOGGER.info("[ws:%s] Client connected", camera_id)

    last_mtime = 0.0

    try:
        while True:
            mtime = frame_store.latest_mtime(camera_id, annotated=True)
            if mtime > last_mtime:
                annotated_jpeg = frame_store.latest_bytes(camera_id, annotated=True)
                if annotated_jpeg:
                    last_mtime = mtime
                    await websocket.send_bytes(annotated_jpeg)
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        LOGGER.debug("[ws:%s] Client error: %s", camera_id, e)
    finally:
        LOGGER.info("[ws:%s] Client disconnected", camera_id)


# ─── MJPEG Fallback (reads from FrameStore) ─────────────────────────────

@app.get("/api/v1/stream/{camera_id}")
async def stream_camera(camera_id: str):
    """MJPEG endpoint — reads latest frame from FrameStore.

    This serves as a fallback for <img> tags that can't do WebSocket.
    No internal key check for this endpoint — cameras serve from FrameStore.
    """
    # Check if camera exists in either StreamManager or CameraManager
    has_stream = stream_manager.get_stream(camera_id) is not None
    has_worker = camera_id in camera_manager._configs
    if not has_stream and not has_worker:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    async def _generate():
        last_mtime = 0.0
        no_frame_count = 0
        try:
            while True:
                mtime = frame_store.latest_mtime(camera_id, annotated=True)
                if mtime > last_mtime:
                    data = frame_store.latest_bytes(camera_id, annotated=True)
                    if data:
                        last_mtime = mtime
                        no_frame_count = 0
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                            b"\r\n" + data + b"\r\n"
                        )
                    else:
                        no_frame_count += 1
                        if no_frame_count > 150:
                            break
                else:
                    no_frame_count += 1
                    if no_frame_count > 150:
                        break
                await asyncio.sleep(0.033)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def main() -> None:
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=reload)


if __name__ == "__main__":
    main()
