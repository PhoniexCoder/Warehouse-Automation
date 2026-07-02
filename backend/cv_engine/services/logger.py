import logging
from datetime import datetime, timezone
from pathlib import Path

from cv_engine.config.settings import SETTINGS
from cv_engine.database import (
    create_tables,
    detection_exists,
    get_current_count,
    get_detections,
    insert_detection,
)
from cv_engine.models.detection_models import TrackedObject

logger = logging.getLogger(__name__)


class DetectionLogger:
    def __init__(self) -> None:
        create_tables()
        log_dir = Path(SETTINGS.project_root) / "data"
        log_dir.mkdir(parents=True, exist_ok=True)

    def log_detection(self, obj: TrackedObject) -> int | None:
        if not obj.counted:
            return None
        if detection_exists(obj.track_id):
            return None

        row_id = insert_detection(
            tracking_id=obj.track_id,
            qr_data=obj.qr_data,
            counted_status=True,
            box_x=obj.x1,
            box_y=obj.y1,
            box_width=obj.width,
            box_height=obj.height,
        )
        logger.info(
            "Logged detection: track_id=%s qr=%s count=%d",
            obj.track_id,
            obj.qr_data or "N/A",
            self.get_current_count(),
        )
        return row_id

    def get_recent_detections(self, limit: int = 50) -> list[dict]:
        return get_detections(limit=limit, counted_only=True)

    def get_current_count(self) -> int:
        return get_current_count()

    def get_all_detections(
        self, limit: int = 100, offset: int = 0, counted_only: bool | None = None
    ) -> list[dict]:
        return get_detections(limit=limit, offset=offset, counted_only=counted_only)
