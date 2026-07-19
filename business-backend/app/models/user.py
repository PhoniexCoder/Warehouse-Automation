from datetime import datetime, timezone
import uuid

from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import enum

from app.database.base import Base


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    OPERATOR = "OPERATOR"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role_enum", create_constraint=True),
        default=UserRole.OPERATOR,
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
