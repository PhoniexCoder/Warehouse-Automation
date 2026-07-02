from datetime import datetime
import uuid

from sqlalchemy import String, Text, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database.base import Base


class AlertType(str, enum.Enum):
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    INVALID_QR = "INVALID_QR"
    DUPLICATE_COUNT = "DUPLICATE_COUNT"
    INVENTORY_MISMATCH = "INVENTORY_MISMATCH"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    type: Mapped[AlertType] = mapped_column(
        SAEnum(AlertType, name="alert_type_enum", create_constraint=True),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SAEnum(AlertSeverity, name="alert_severity_enum", create_constraint=True),
        nullable=False,
        default=AlertSeverity.WARNING,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
