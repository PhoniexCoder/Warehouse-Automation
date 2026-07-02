import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database.base import Base, pk_uuid


class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[uuid.UUID] = pk_uuid()
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tracking_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    qr_data: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="detection | invalid_qr | duplicate"
    )
    counted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    box_x: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    box_y: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    box_width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    box_height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    inventory_item = relationship("InventoryItem", back_populates="movements")
    warehouse = relationship("Warehouse", back_populates="movements")
    camera = relationship("Camera", back_populates="movements")
