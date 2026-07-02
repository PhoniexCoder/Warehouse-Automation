from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class AlertResponse(BaseModel):
    id: uuid.UUID
    type: str
    message: str
    severity: str
    timestamp: datetime

    model_config = {"from_attributes": True}
