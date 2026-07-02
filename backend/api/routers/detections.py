import logging

from fastapi import APIRouter, HTTPException, Query

from api.schemas import DetectionEventRequest, DetectionResponse
from cv_engine.database import get_all_detections, save_detection

LOGGER = logging.getLogger("api.routers.detections")

router = APIRouter(tags=["Detections"])


@router.post(
    "/detection-event",
    status_code=201,
    summary="Log a detection event",
)
def create_detection_event(body: DetectionEventRequest) -> dict:
    try:
        record = save_detection(
            tracking_id=body.tracking_id,
            qr_data=body.qr_data,
            camera_id=body.camera_id,
            counted_status=body.counted,
            box_x=body.box_x,
            box_y=body.box_y,
            box_width=body.box_width,
            box_height=body.box_height,
        )
        LOGGER.info(
            "Detection logged: tracking_id=%s qr_data=%s camera=%s counted=%s",
            body.tracking_id, body.qr_data, body.camera_id, body.counted,
        )
        return {
            "success": True,
            "data": DetectionResponse.model_validate(record).model_dump(mode="json"),
            "error": None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Failed to log detection")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/detections",
    summary="List logged detection events",
)
def list_detections(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    counted_only: bool | None = Query(None),
) -> dict:
    try:
        records = get_all_detections(limit=limit, offset=offset, counted_only=counted_only)
        return {
            "success": True,
            "data": [DetectionResponse.model_validate(r).model_dump(mode="json") for r in records],
            "error": None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Failed to list detections")
        raise HTTPException(status_code=500, detail=str(exc))
