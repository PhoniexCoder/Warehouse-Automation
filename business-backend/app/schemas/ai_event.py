from datetime import datetime
import enum

from pydantic import BaseModel, Field


class MovementTypeEnum(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class DetectionEventPayload(BaseModel):
    tracking_id: int = Field(..., gt=0, examples=[12])
    qr_data: str | None = Field(None, examples=["BOX-1024"])
    camera_id: str = Field(..., examples=["cam_1"])
    counted: bool = Field(True)
    movement_type: MovementTypeEnum = Field(MovementTypeEnum.ENTRY, examples=["ENTRY"])
    timestamp: datetime | None = Field(None)


class InvalidQrEventPayload(BaseModel):
    tracking_id: int = Field(..., gt=0, examples=[15])
    error_type: str = Field("NO_QR", examples=["NO_QR", "INVALID_QR", "DAMAGED_QR"])
    camera_id: str = Field(..., examples=["cam_1"])
    timestamp: datetime | None = Field(None)
