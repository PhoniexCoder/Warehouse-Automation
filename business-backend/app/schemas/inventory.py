from datetime import datetime
import uuid
import enum

from pydantic import BaseModel, Field


class SyncMovementTypeEnum(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class InventorySyncRequest(BaseModel):
    qr_data: str = Field(..., min_length=1, max_length=255, examples=["BOX-1024"])
    camera_id: str = Field(..., examples=["cam_1"])
    movement_type: SyncMovementTypeEnum = Field(SyncMovementTypeEnum.ENTRY)


class InventorySyncResponse(BaseModel):
    matched: bool
    product_code: str | None = None
    product_name: str | None = None
    quantity_before: int | None = None
    quantity_after: int | None = None
    alert_generated: bool = False
    alert_id: str | None = None
    movement_type: str


class InventoryCreate(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=255, examples=["PROD-001"])
    product_name: str = Field(..., min_length=1, max_length=500, examples=["Steel Brackets"])
    quantity: int = Field(0, ge=0)
    warehouse_id: uuid.UUID


class InventoryUpdate(BaseModel):
    product_name: str | None = None
    quantity: int | None = Field(None, ge=0)


class InventoryResponse(BaseModel):
    id: uuid.UUID
    product_code: str
    product_name: str
    quantity: int
    warehouse_id: uuid.UUID
    updated_at: datetime

    model_config = {"from_attributes": True}
