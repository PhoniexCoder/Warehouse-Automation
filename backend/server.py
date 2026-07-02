import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import v1_router
from api.exceptions import general_exception_handler, validation_exception_handler
from cv_engine.database import create_tables
from cv_engine.orchestration.camera_manager import CameraManager
from fastapi.exceptions import RequestValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

LOGGER = logging.getLogger("server")

camera_manager = CameraManager()

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


@app.on_event("startup")
def _startup() -> None:
    create_tables()
    LOGGER.info("Database tables ensured")

    camera_manager.add_camera("cam_1", {
        "source_type": "simulated",
        "sim_scene": "entry",
        "line_y": 620,
        "display_name": "Entry Gate",
    })
    camera_manager.add_camera("cam_2", {
        "source_type": "simulated",
        "sim_scene": "conveyor",
        "line_y": 400,
        "display_name": "Conveyor Belt",
    })
    camera_manager.add_camera("cam_3", {
        "source_type": "simulated",
        "sim_scene": "storage",
        "line_y": 500,
        "display_name": "Storage Area",
    })
    camera_manager.add_camera("cam_4", {
        "source_type": "simulated",
        "sim_scene": "exit",
        "line_y": 600,
        "display_name": "Exit Dock",
    })

    camera_manager.start_all()
    LOGGER.info("CameraManager started with 4 simulated cameras")


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


def main() -> None:
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
