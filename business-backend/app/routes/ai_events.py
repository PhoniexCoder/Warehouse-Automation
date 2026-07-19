import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.ai_event import DetectionEventPayload, InvalidQrEventPayload
from app.schemas.common import ApiResponse
from app.services.ai_event_processor import AiEventProcessor
from app.auth.permissions import _verify_internal_key

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["AI Events"])


@router.post("/events/detection", status_code=201, summary="Receive detection from AI engine")
async def receive_detection(
    body: DetectionEventPayload,
    session: AsyncSession = Depends(get_session),
    _key: None = Depends(_verify_internal_key),
) -> ApiResponse:
    processor = AiEventProcessor(session)
    result = await processor.process_detection(
        tracking_id=body.tracking_id,
        camera_id=body.camera_id,
        counted=body.counted,
        qr_data=body.qr_data,
        movement_type=body.movement_type,
        timestamp=body.timestamp,
    )
    return ApiResponse(success=True, data=result)


@router.post("/events/invalid-qr", status_code=201, summary="Receive invalid QR from AI engine")
async def receive_invalid_qr(
    body: InvalidQrEventPayload,
    session: AsyncSession = Depends(get_session),
    _key: None = Depends(_verify_internal_key),
) -> ApiResponse:
    processor = AiEventProcessor(session)
    result = await processor.process_invalid_qr(
        tracking_id=body.tracking_id,
        error_type=body.error_type,
        camera_id=body.camera_id,
        timestamp=body.timestamp,
    )
    return ApiResponse(success=True, data=result)
