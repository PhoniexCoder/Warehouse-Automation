from fastapi import APIRouter

from app.routes import (
    ai_events,
    warehouses,
    cameras,
    boxes,
    inventory,
    count_logs,
    alerts,
    audit_logs,
    dashboard,
    auth,
)

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(auth.router)
v1_router.include_router(ai_events.router)
v1_router.include_router(warehouses.router)
v1_router.include_router(cameras.router)
v1_router.include_router(boxes.router)
v1_router.include_router(inventory.router)
v1_router.include_router(count_logs.router)
v1_router.include_router(alerts.router)
v1_router.include_router(audit_logs.router)
v1_router.include_router(dashboard.router)

__all__ = ["v1_router"]
