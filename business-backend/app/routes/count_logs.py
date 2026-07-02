import uuid
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.count_log import MovementType
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.count_log import CountLogResponse
from app.services.count_log_service import CountLogService
from app.auth.permissions import require_manager_up

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Count Logs"])


@router.get("/count-logs", summary="List count log entries")
async def list_count_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    box_id: uuid.UUID | None = None,
    camera_id: str | None = None,
    movement_type: str | None = None,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = CountLogService(session)
    mtype = MovementType(movement_type) if movement_type else None
    logs = await service.list_all(
        limit=limit,
        offset=offset,
        box_id=box_id,
        camera_id=camera_id,
        movement_type=mtype,
    )
    return ApiResponse(
        success=True,
        data=[CountLogResponse.model_validate(log).model_dump(mode="json") for log in logs],
    )
