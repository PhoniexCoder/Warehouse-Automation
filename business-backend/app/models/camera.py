from datetime import datetime, timezone
import uuid

from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database.base import Base


class CameraStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    OFFLINE = "offline"


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True,
    )
    stream_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[CameraStatus] = mapped_column(
        SAEnum(CameraStatus, name="camera_status_enum", create_constraint=True),
        default=CameraStatus.ACTIVE,
        nullable=False,
    )
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    warehouse = relationship("Warehouse", back_populates="cameras")
