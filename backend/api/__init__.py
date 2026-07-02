from fastapi import APIRouter

from api.routers import detections, events, status

v1_router = APIRouter()

v1_router.include_router(detections.router)
v1_router.include_router(events.router)
v1_router.include_router(status.router)


__all__ = ["v1_router"]
