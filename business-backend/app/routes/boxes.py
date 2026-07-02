import uuid
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.box import BoxStatus
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.box import BoxResponse, BoxDetail, CountLogSummary
from app.services.box_service import BoxService
from app.services.count_log_service import CountLogService
from app.auth.permissions import require_manager_up

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Boxes"])


@router.get("/boxes", summary="List boxes")
async def list_boxes(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    status: str | None = None,
    camera_id: str | None = None,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = BoxService(session)
    status_enum = BoxStatus(status) if status else None
    boxes = await service.list_all(limit=limit, offset=offset, status=status_enum, camera_id=camera_id)
    return ApiResponse(
        success=True,
        data=[BoxResponse.model_validate(b).model_dump(mode="json") for b in boxes],
    )


@router.get("/boxes/{box_id}", summary="Get box with count logs")
async def get_box(
    box_id: uuid.UUID,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = BoxService(session)
    count_service = CountLogService(session)
    box = await service.get(box_id)
    logs = await count_service.list_all(box_id=box_id)
    detail = BoxDetail(
        **BoxResponse.model_validate(box).model_dump(),
        count_logs=[
            CountLogSummary(
                id=log.id,
                movement_type=log.movement_type.value,
                camera_id=log.camera_id,
                timestamp=log.timestamp,
            )
            for log in logs
        ],
    )
    return ApiResponse(success=True, data=detail.model_dump(mode="json"))


@router.get("/boxes/by-tracking/{tracking_id}", summary="Find box by tracking ID")
async def get_box_by_tracking(
    tracking_id: int,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = BoxService(session)
    box = await service.get_by_tracking_id(tracking_id)
    if not box:
        return ApiResponse(success=True, data=None)
    return ApiResponse(
        success=True,
        data=BoxResponse.model_validate(box).model_dump(mode="json"),
    )


@router.get("/boxes/by-qr/{qr_data}", summary="Find boxes by QR code")
async def get_boxes_by_qr(
    qr_data: str,
    _mgr: User = Depends(require_manager_up),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = BoxService(session)
    boxes = await service.get_by_qr(qr_data)
    return ApiResponse(
        success=True,
        data=[BoxResponse.model_validate(b).model_dump(mode="json") for b in boxes],
    )
