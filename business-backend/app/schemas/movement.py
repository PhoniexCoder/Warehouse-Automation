from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class MovementResponse(BaseModel):
    id: uuid.UUID
    inventory_item_id: uuid.UUID
    warehouse_id: uuid.UUID | None
    camera_id: uuid.UUID | None
    tracking_id: int
    qr_data: str | None
    event_type: str
    counted: bool
    timestamp: datetime
    box_x: int
    box_y: int
    box_width: int
    box_height: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MovementFilter(BaseModel):
    tracking_id: int | None = Field(None, gt=0)
    warehouse_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    event_type: str | None = None
    counted: bool | None = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
