import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.models.user import User, UserRole
from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    REFRESH_TOKEN_KEY,
)

LOGGER = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        username: str,
        email: str,
        password: str,
        role: UserRole = UserRole.OPERATOR,
    ) -> User:
        existing = await self._get_by_username(username)
        if existing:
            raise ConflictError(f"Username already exists: {username}")
        existing_email = await self._get_by_email(email)
        if existing_email:
            raise ConflictError(f"Email already exists: {email}")

        user = User(
            username=username,
            email=email,
            hashed_password=_hash_password(password),
            role=role,
        )
        self._session.add(user)
        await self._session.flush()
        LOGGER.info("User registered: %s (role=%s)", username, role.value)
        return user

    async def authenticate(self, username: str, password: str) -> tuple[str, str, User]:
        user = await self._get_by_username(username)
        if not user:
            raise UnauthorizedError("Invalid username or password")
        if not user.is_active:
            raise UnauthorizedError("Account is disabled")

        if not _verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid username or password")

        access_token = create_access_token(
            subject=str(user.id), role=user.role.value,
        )
        refresh_token = create_refresh_token(subject=str(user.id))

        LOGGER.info("User authenticated: %s", username)
        return access_token, refresh_token, user

    async def refresh_tokens(self, refresh_token: str) -> tuple[str, str]:
        payload = decode_token(refresh_token)
        if payload.get("type") != REFRESH_TOKEN_KEY:
            raise UnauthorizedError("Invalid refresh token")

        user_id = payload.get("sub")
        user = await self.get(uuid.UUID(user_id))

        access_token = create_access_token(
            subject=str(user.id), role=user.role.value,
        )
        new_refresh = create_refresh_token(subject=str(user.id))
        return access_token, new_refresh

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise NotFoundError("User", str(user_id))
        return user

    async def list_all(self) -> list[User]:
        stmt = select(User).order_by(User.username)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_role(self, user_id: uuid.UUID, role: UserRole) -> User:
        user = await self.get(user_id)
        user.role = role
        await self._session.flush()
        LOGGER.info("User role updated: %s -> %s", user.username, role.value)
        return user

    async def deactivate(self, user_id: uuid.UUID) -> User:
        user = await self.get(user_id)
        user.is_active = False
        await self._session.flush()
        LOGGER.info("User deactivated: %s", user.username)
        return user

    async def change_password(
        self, user_id: uuid.UUID, current_password: str, new_password: str
    ) -> User:
        user = await self.get(user_id)
        if not _verify_password(current_password, user.hashed_password):
            raise UnauthorizedError("Current password is incorrect")
        user.hashed_password = _hash_password(new_password)
        await self._session.flush()
        LOGGER.info("Password changed: %s", user.username)
        return user

    async def _get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
