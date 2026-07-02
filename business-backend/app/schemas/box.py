from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class BoxResponse(BaseModel):
    id: uuid.UUID
    tracking_id: int
    qr_data: str | None
    camera_id: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class BoxDetail(BoxResponse):
    count_logs: list[CountLogSummary] = []


class CountLogSummary(BaseModel):
    id: uuid.UUID
    movement_type: str
    camera_id: str
    timestamp: datetime

    model_config = {"from_attributes": True}
