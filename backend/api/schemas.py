from datetime import datetime

from pydantic import BaseModel, Field


class DetectionEventRequest(BaseModel):
    tracking_id: int = Field(..., gt=0, examples=[12])
    qr_data: str | None = Field(None, examples=["BOX-1024"])
    counted: bool = Field(True, description="Whether the box crossed the counting line")
    camera_id: str = Field("camera_01", examples=["cam_1"])
    box_x: int = Field(0, ge=0)
    box_y: int = Field(0, ge=0)
    box_width: int = Field(0, ge=0)
    box_height: int = Field(0, ge=0)


class InvalidQrEventRequest(BaseModel):
    tracking_id: int = Field(..., gt=0, examples=[12])
    error_type: str = Field("NO_QR", examples=["NO_QR", "INVALID_QR", "DAMAGED_QR"])
    camera_id: str = Field("camera_01", examples=["cam_1"])
    box_x: int = Field(0, ge=0)
    box_y: int = Field(0, ge=0)
    box_width: int = Field(0, ge=0)
    box_height: int = Field(0, ge=0)


class DetectionResponse(BaseModel):
    id: int
    tracking_id: int
    qr_data: str | None
    timestamp: datetime
    camera_id: str
    counted_status: bool
    box_x: int
    box_y: int
    box_width: int
    box_height: int

    model_config = {"from_attributes": True}


class InvalidQrEventResponse(BaseModel):
    id: int
    tracking_id: int
    error_type: str
    camera_id: str
    timestamp: datetime
    box_x: int
    box_y: int
    box_width: int
    box_height: int

    model_config = {"from_attributes": True}


class TotalCountResponse(BaseModel):
    total_count: int


class HealthResponse(BaseModel):
    status: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    data: None = None
    error: ErrorDetail
