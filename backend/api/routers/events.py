import logging

from fastapi import APIRouter, HTTPException

from api.schemas import InvalidQrEventRequest, InvalidQrEventResponse
from cv_engine.database import save_invalid_qr

LOGGER = logging.getLogger("api.routers.events")

router = APIRouter(tags=["Events"])


@router.post(
    "/invalid-qr-event",
    status_code=201,
    summary="Log an invalid (unreadable) QR event",
)
def create_invalid_qr_event(body: InvalidQrEventRequest) -> dict:
    try:
        record = save_invalid_qr(
            tracking_id=body.tracking_id,
            error_type=body.error_type,
            camera_id=body.camera_id,
            box_x=body.box_x,
            box_y=body.box_y,
            box_width=body.box_width,
            box_height=body.box_height,
        )
        LOGGER.info("Invalid QR logged: tracking_id=%s camera=%s", body.tracking_id, body.camera_id)
        return {
            "success": True,
            "data": InvalidQrEventResponse.model_validate(record).model_dump(mode="json"),
            "error": None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Failed to log invalid QR event")
        raise HTTPException(status_code=500, detail=str(exc))
