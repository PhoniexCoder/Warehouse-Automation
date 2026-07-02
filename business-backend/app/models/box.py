from datetime import datetime, timezone
import uuid

from sqlalchemy import String, Integer, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database.base import Base


class BoxStatus(str, enum.Enum):
    IN_TRANSIT = "in_transit"
    STORED = "stored"
    DISPATCHED = "dispatched"
    LOST = "lost"


class Box(Base):
    __tablename__ = "boxes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tracking_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
    )
    qr_data: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
    )
    camera_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="AI engine camera_id (e.g. cam_1)",
    )
    status: Mapped[BoxStatus] = mapped_column(
        SAEnum(BoxStatus, name="box_status_enum", create_constraint=True),
        default=BoxStatus.IN_TRANSIT,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    count_logs = relationship("CountLog", back_populates="box", cascade="all, delete-orphan")
