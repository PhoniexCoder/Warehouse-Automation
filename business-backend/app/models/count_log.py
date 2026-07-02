from datetime import datetime
import uuid

from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database.base import Base


class MovementType(str, enum.Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class CountLog(Base):
    __tablename__ = "count_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    box_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boxes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="AI engine camera_id (e.g. cam_1)",
    )
    movement_type: Mapped[MovementType] = mapped_column(
        SAEnum(MovementType, name="movement_type_enum", create_constraint=True),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    box = relationship("Box", back_populates="count_logs")
