from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class NvrCreate(BaseModel):
    warehouse_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255, examples=["Main Building NVR"])
    ip_address: str = Field(..., examples=["192.168.1.35"])
    port: int = Field(default=34567, examples=[34567])
    protocol: str = Field(default="dvrip", examples=["dvrip"])
    username: str | None = Field(default=None, examples=["admin"])
    password: str | None = Field(default=None)
    is_tailscale: bool = False


class NvrUpdate(BaseModel):
    name: str | None = None
    ip_address: str | None = None
    port: int | None = None
    protocol: str | None = None
    username: str | None = None
    password: str | None = None
    is_tailscale: bool | None = None
    status: str | None = None


class NvrResponse(BaseModel):
    id: uuid.UUID
    warehouse_id: uuid.UUID
    name: str
    ip_address: str
    port: int
    protocol: str
    is_tailscale: bool
    status: str
    camera_count: int | None = None
    last_seen: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class CheckIpRequest(BaseModel):
    ip: str = Field(..., examples=["100.64.0.5"])
    port: int = Field(default=34567, examples=[34567])


class CheckIpResponse(BaseModel):
    ip: str
    reachable: bool
    has_dvrip: bool
    has_rtsp: bool


class NvrDiscoverRequest(BaseModel):
    ip: str = Field(..., examples=["192.168.1.35"])
    port: int = Field(default=34567, examples=[34567])
    username: str = Field(..., examples=["admin"])
    password: str = Field(..., examples=["admin"])


class NvrChannelInfo(BaseModel):
    channel_id: int
    display_name: str
    stream_url: str
    protocol: str
    active: bool = False


class NvrDiscoverResponse(BaseModel):
    nvr_info: dict
    all_channels: list[NvrChannelInfo]
    active_channels: list[NvrChannelInfo]
