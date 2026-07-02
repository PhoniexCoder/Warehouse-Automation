from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: str | None
    action: str
    timestamp: datetime

    model_config = {"from_attributes": True}
