from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class CameraCreate(BaseModel):
    warehouse_id: uuid.UUID
    camera_name: str = Field(..., min_length=1, max_length=255, examples=["Entry Gate Camera"])
    stream_url: str = Field(..., examples=["rtsp://192.168.1.100:554/stream1"])
    status: str | None = None


class CameraUpdate(BaseModel):
    camera_name: str | None = None
    stream_url: str | None = None
    status: str | None = None


class CameraResponse(BaseModel):
    id: uuid.UUID
    warehouse_id: uuid.UUID
    camera_name: str
    stream_url: str
    status: str
    last_seen: datetime | None

    model_config = {"from_attributes": True}


class VmsScanRequest(BaseModel):
    ip: str
    username: str
    password: str


class VmsImportRequest(BaseModel):
    warehouse_id: uuid.UUID
    ip: str
    username: str
    password: str
    channels: list[int]


class DvripConnectRequest(BaseModel):
    warehouse_id: uuid.UUID
    host: str = Field(..., examples=["192.168.1.35"])
    username: str = Field(..., examples=["uxdp"])
    password: str = Field(..., examples=["cw8adc"])
