import os
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.auth.user_service import _hash_password

LOGGER = logging.getLogger(__name__)

SUPER_ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "superadmin")
SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "superadmin@warehouse.local")
SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD", "")


async def seed_super_admin(session: AsyncSession) -> None:
    if not SUPER_ADMIN_PASSWORD:
        LOGGER.warning("SUPER_ADMIN_PASSWORD not set, skipping super admin seed")
        return

    stmt = select(User).where(User.role == UserRole.SUPER_ADMIN)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        LOGGER.info("Super admin already exists: %s (%s)", existing.username, existing.id)
        return

    stmt_user = select(User).where(User.username == SUPER_ADMIN_USERNAME)
    result_user = await session.execute(stmt_user)
    username_taken = result_user.scalar_one_or_none()

    if username_taken:
        username_taken.role = UserRole.SUPER_ADMIN
        await session.flush()
        LOGGER.info("Promoted existing user '%s' to SUPER_ADMIN (%s)",
                     SUPER_ADMIN_USERNAME, username_taken.id)
        return

    user = User(
        username=SUPER_ADMIN_USERNAME,
        email=SUPER_ADMIN_EMAIL,
        hashed_password=_hash_password(SUPER_ADMIN_PASSWORD),
        role=UserRole.SUPER_ADMIN,
    )
    session.add(user)
    await session.flush()
    LOGGER.info("Super admin created: %s (id=%s)", SUPER_ADMIN_USERNAME, user.id)
