import logging

import httpx
from fastapi import APIRouter, Depends, Query

from app.models.user import User
from app.schemas.common import ApiResponse
from app.auth.permissions import require_manager_up

LOGGER = logging.getLogger(__name__)

CV_ENGINE_URL = "http://localhost:8000/api/v1"

router = APIRouter(tags=["Detections"])


@router.get("/detections", summary="List detection events from CV engine")
async def list_detections(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _mgr: User = Depends(require_manager_up),
) -> ApiResponse:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{CV_ENGINE_URL}/detections",
                params={"limit": limit, "offset": offset},
            )
            if resp.status_code == 200:
                data = resp.json()
                return ApiResponse(success=True, data=data.get("data", []))
            return ApiResponse(success=False, data=[])
    except Exception as e:
        LOGGER.warning("Could not fetch detections from CV engine: %s", e)
        return ApiResponse(success=True, data=[])
