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

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@warehouse.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


async def seed_super_admin(session: AsyncSession) -> None:
    # Seed Super Admin
    if SUPER_ADMIN_PASSWORD:
        stmt = select(User).where(User.username == SUPER_ADMIN_USERNAME)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if not existing:
            user = User(
                username=SUPER_ADMIN_USERNAME,
                email=SUPER_ADMIN_EMAIL,
                hashed_password=_hash_password(SUPER_ADMIN_PASSWORD),
                role=UserRole.SUPER_ADMIN,
            )
            session.add(user)
            LOGGER.info("Super admin created: %s", SUPER_ADMIN_USERNAME)

    # Seed Admin
    if ADMIN_PASSWORD:
        stmt = select(User).where(User.username == ADMIN_USERNAME)
        result = await session.execute(stmt)
        existing_admin = result.scalar_one_or_none()
        if not existing_admin:
            admin_user = User(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                hashed_password=_hash_password(ADMIN_PASSWORD),
                role=UserRole.ADMIN,
            )
            session.add(admin_user)
            LOGGER.info("Admin user created: %s", ADMIN_USERNAME)

    await session.flush()
