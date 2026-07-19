from collections.abc import AsyncGenerator
import uuid
import logging

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SETTINGS
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.database.session import get_session
from app.auth.user_service import UserService
from app.auth.jwt_handler import decode_token
from app.models.user import User, UserRole

LOGGER = logging.getLogger(__name__)


async def get_current_user(
    authorization: str = Header(..., description="Bearer <token>"),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Invalid authorization header")

    token = authorization[len("Bearer "):]
    try:
        payload = decode_token(token)
    except Exception:
        raise UnauthorizedError("Invalid or expired token")

    user_id = payload.get("sub")
    token_type = payload.get("type")
    if not user_id or token_type != "access":
        raise UnauthorizedError("Invalid token type")

    service = UserService(session)
    user = await service.get(uuid.UUID(user_id))
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")
    return user


async def _verify_internal_key(x_internal_key: str = Header(..., alias="X-Internal-Key")) -> None:
    if x_internal_key != SETTINGS.internal_api_key:
        raise UnauthorizedError("Invalid internal API key")


class RoleChecker:
    def __init__(self, *allowed_roles: UserRole) -> None:
        self._allowed = set(allowed_roles)

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        if user.role == UserRole.SUPER_ADMIN:
            return user
        if user.role not in self._allowed:
            LOGGER.warning(
                "Forbidden: user=%s role=%s required=%s",
                user.username, user.role.value,
                [r.value for r in self._allowed],
            )
            raise ForbiddenError(
                f"Requires one of: {', '.join(r.value for r in self._allowed)}",
            )
        return user


require_super_admin = RoleChecker(UserRole.SUPER_ADMIN)
require_admin = RoleChecker(UserRole.SUPER_ADMIN, UserRole.ADMIN)
require_manager_up = RoleChecker(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MANAGER)
require_any = RoleChecker(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MANAGER, UserRole.OPERATOR)
