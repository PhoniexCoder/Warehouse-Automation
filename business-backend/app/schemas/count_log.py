from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class CountLogResponse(BaseModel):
    id: uuid.UUID
    box_id: uuid.UUID
    camera_id: str
    movement_type: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class CountLogFilter(BaseModel):
    box_id: uuid.UUID | None = None
    camera_id: str | None = None
    movement_type: str | None = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)
