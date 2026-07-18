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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api import v1_router
from api.exceptions import general_exception_handler, validation_exception_handler
from cv_engine.database import create_tables
from cv_engine.orchestration.camera_manager import CameraManager
from cv_engine.orchestration.frame_store import FrameStore
from fastapi.exceptions import RequestValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

LOGGER = logging.getLogger("server")

camera_manager = CameraManager()
frame_store = FrameStore()

app = FastAPI(title="Warehouse AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.include_router(v1_router, prefix="/api/v1")


import hashlib
import json
import requests
import threading
import time

BUSINESS_BACKEND_URL = os.getenv("BUSINESS_BACKEND_URL", "http://localhost:8001")


def _config_hash(config: dict) -> str:
    keys = {"model_path", "roi", "source_type", "channel", "source", "detection_conf", "count_conf"}
    snapshot = {k: config.get(k) for k in sorted(keys)}
    return hashlib.md5(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()

def sync_cameras_loop():
    # Wait for both servers to be fully booted
    time.sleep(5)
    LOGGER.info("VMS Sync loop started")
    while True:
        try:
            url = f"{BUSINESS_BACKEND_URL}/api/v1/cameras/internal/active"
            res = requests.get(url, timeout=5)
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

                            if stream_url.startswith("dvrip://"):
                                from urllib.parse import urlparse, parse_qs
                                parsed = urlparse(stream_url)
                                params = parse_qs(parsed.query)
                                if "channel" in params:
                                    channel = int(params["channel"][0])
                                elif parsed.path:
                                    channel = int(parsed.path.strip("/"))
                                else:
                                    channel = 0
                                if channel > 8:
                                    LOGGER.debug("VMS: Skipping %s ch%d (go2rtc only has ch0-ch8)", cam.get("camera_name"), channel)
                                    continue
                                config = {
                                    "source_type": "dvrip",
                                    "channel": channel,
                                    "line_y": 500,
                                    "display_name": cam.get("camera_name", ""),
                                    "target_fps": 5,
                                    "frame_skip": 2,
                                    "model_path": cam.get("model_path") or "",
                                    "roi": cam.get("roi"),
                                    "detection_conf": 0.55,
                                    "count_conf": 0.65,
                                }
                            else:
                                config = {
                                    "source_type": "rtsp",
                                    "source": stream_url,
                                    "line_y": 500,
                                    "display_name": cam.get("camera_name", ""),
                                    "target_fps": 5,
                                    "frame_skip": 2,
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
                                    LOGGER.info("VMS: Config changed for %s (roi/model), restarting worker",
                                                 cam.get("camera_name"))
                                    camera_manager.stop_camera(cam_id)
                                    camera_manager.start_camera(cam_id, config)
                                else:
                                    health = camera_manager._health.get(cam_id, {})
                                    status = health.get("status", "")
                                    if status in ("dead", "stopped"):
                                        LOGGER.info("VMS: Retrying dead camera %s (%s)", cam.get("camera_name"), cam_id)
                                        camera_manager.stop_camera(cam_id)
                                        camera_manager.start_camera(cam_id, config)
                            else:
                                config["_hash"] = _config_hash(config)
                                LOGGER.info("VMS: Starting camera worker for %s (%s) [%s]",
                                             cam.get("camera_name"), cam_id, config["source_type"])
                                camera_manager.start_camera(cam_id, config)
                        except Exception:
                            LOGGER.exception("VMS: Failed to start worker for camera %s", cam.get("id", "?"))
                    
                    configured_ids = list(camera_manager._configs.keys())
                    for c_id in configured_ids:
                        if c_id not in active_ids:
                            LOGGER.info("VMS: Stopping camera worker for %s", c_id)
                            camera_manager.stop_camera(c_id)
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
    LOGGER.info("Shutting down CameraManager")
    camera_manager.stop_all()


@app.get("/api/v1/cameras")
def get_cameras() -> dict:
    return {
        "success": True,
        "data": camera_manager.get_status(),
        "error": None,
    }


@app.get("/api/v1/stream/{camera_id}")
async def stream_camera(camera_id: str):
    cameras = camera_manager.get_status().get("cameras", {})
    if camera_id not in cameras:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    async def _generate():
        last_mtime = 0.0
        no_frame_count = 0
        try:
            while True:
                mtime = frame_store.latest_mtime(camera_id)
                if mtime > last_mtime:
                    data = frame_store.latest_bytes(camera_id)
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
                            LOGGER.warning("No frames for camera %s after 5s, closing stream", camera_id)
                            break
                else:
                    no_frame_count += 1
                    if no_frame_count > 150:
                        LOGGER.warning("No frames for camera %s after 5s, closing stream", camera_id)
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
