from datetime import datetime
import uuid

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Main Warehouse"])
    location: str = Field(..., min_length=1, max_length=500, examples=["123 Industrial Blvd"])


class WarehouseUpdate(BaseModel):
    name: str | None = None
    location: str | None = None


class WarehouseResponse(BaseModel):
    id: uuid.UUID
    name: str
    location: str
    created_at: datetime

    model_config = {"from_attributes": True}
