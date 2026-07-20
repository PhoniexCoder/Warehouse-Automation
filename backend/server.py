import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

if "OPENCV_FFMPEG_CAPTURE_OPTIONS" not in os.environ:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import asyncio
import logging
import multiprocessing
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
from urllib.parse import urlparse

BUSINESS_BACKEND_URL = os.getenv("BUSINESS_BACKEND_URL", "http://localhost:8001")
GO2RTC_RTSP_URL = os.getenv("GO2RTC_RTSP_URL", "http://host.docker.internal:554")
# Extract host:port from GO2RTC_RTSP_URL for RTSP stream construction
_GO2RTC_HOST = GO2RTC_RTSP_URL.replace("http://", "").replace("https://", "").rstrip("/")

_DVRIP_URL_RE = re.compile(r"^dvrip://([^:]+):([^@]+)@([^:]+):(\d+)/(\d+)$")
_RTSP_URL_RE = re.compile(r"^rtsp://")


def _verify_cv_internal_key(x_internal_key: str = Header(..., alias="X-Internal-Key")) -> None:
    if x_internal_key != _CV_INTERNAL_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")


def _config_hash(config: dict) -> str:
    keys = {"model_path", "roi", "source_type", "source", "detection_conf", "count_conf"}
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


def sync_cameras_loop():
    time.sleep(5)
    LOGGER.info("VMS Sync loop started (go2rtc bridge mode)")
    while True:
        try:
            url = f"{BUSINESS_BACKEND_URL}/api/v1/cameras/internal/active"
            res = requests.get(url, timeout=5, headers={"X-Internal-Key": _CV_INTERNAL_KEY})
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    active_cameras = data["data"]
                    active_ids = set()

                    # Group DVRIP cameras by NVR host:port for staggered startup
                    dvrip_cameras = []
                    rtsp_cameras = []

                    for cam in active_cameras:
                        try:
                            cam_id = cam["id"]
                            stream_url = cam.get("stream_url", "")
                            active_ids.add(cam_id)

                            if not stream_url:
                                continue

                            if stream_url.startswith("dvrip://"):
                                dvrip_cameras.append(cam)
                            else:
                                rtsp_cameras.append(cam)
                        except Exception:
                            LOGGER.exception("VMS: Failed to process camera %s", cam.get("id", "?"))

                    # Route ALL cameras through go2rtc RTSP (both DVRIP and native RTSP)
                    # go2rtc handles DVRIP protocol natively — cv-engine reads RTSP from go2rtc
                    all_cameras = dvrip_cameras + rtsp_cameras

                    for cam in all_cameras:
                        try:
                            cam_id = cam["id"]
                            stream_url = cam.get("stream_url", "")

                            if not stream_url:
                                continue

                            # For DVRIP cameras: read RTSP from go2rtc (go2rtc handles DVRIP protocol)
                            # For native RTSP cameras: read directly from the RTSP URL
                            if stream_url.startswith("dvrip://"):
                                go2rtc_rtsp = f"rtsp://{_GO2RTC_HOST}/{cam_id}"
                                rtsp_source = go2rtc_rtsp
                            else:
                                rtsp_source = stream_url

                            # Start RTSP stream through StreamManager (unified WebSocket delivery)
                            stream_manager.start_camera_rtsp(
                                camera_id=cam_id,
                                rtsp_url=rtsp_source,
                            )

                            # Start detection worker (reads from FrameStore)
                            config = {
                                "source_type": "file_store",
                                "line_y": 500,
                                "display_name": cam.get("camera_name", ""),
                                "target_fps": 5,
                                "model_path": cam.get("model_path") or "",
                                "roi": cam.get("roi"),
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
                                LOGGER.info("VMS: Starting camera worker for %s (%s) [go2rtc-rtsp->file_store]",
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

                    # Stop streams for inactive cameras (both DVRIP and RTSP)
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
