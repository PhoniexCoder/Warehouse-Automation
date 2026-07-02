import logging

from fastapi import APIRouter

from api.schemas import HealthResponse, TotalCountResponse
from cv_engine.database import get_total_count

LOGGER = logging.getLogger("api.routers.status")

router = APIRouter(tags=["Status"])


@router.get(
    "/total-count",
    summary="Get total distinct box count",
)
def total_count() -> dict:
    count = get_total_count()
    return {
        "success": True,
        "data": TotalCountResponse(total_count=count).model_dump(),
        "error": None,
    }


@router.get(
    "/health",
    summary="Health check",
)
def health() -> dict:
    return {
        "success": True,
        "data": HealthResponse(status="running").model_dump(),
        "error": None,
    }
