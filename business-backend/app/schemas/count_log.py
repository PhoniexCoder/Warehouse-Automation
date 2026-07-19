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
