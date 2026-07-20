import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.schemas.common import ApiResponse
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    ChangePasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.user_service import UserService
from app.auth.permissions import require_admin, require_super_admin, get_current_user
from app.models.user import UserRole, User

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["Auth"])

ROLE_LEVELS = {
    UserRole.SUPER_ADMIN: 4,
    UserRole.ADMIN: 3,
    UserRole.MANAGER: 2,
    UserRole.OPERATOR: 1,
}


class UpdateRoleRequest(BaseModel):
    role: str


@router.post("/register", status_code=201, summary="Register a new user (admin only)")
async def register(
    body: RegisterRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    requested_role = UserRole[body.role.value]
    admin_level = ROLE_LEVELS.get(admin.role, 0)
    requested_level = ROLE_LEVELS.get(requested_role, 0)
    if requested_level > admin_level:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot create user with role '{requested_role.value}' higher than your role '{admin.role.value}'"
        )
    service = UserService(session)
    user = await service.register(
        username=body.username,
        email=body.email,
        password=body.password,
        role=requested_role,
    )
    return ApiResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(mode="json"),
    )


@router.post("/login", summary="Authenticate and get tokens")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    access_token, refresh_token, user = await service.authenticate(
        username=body.username,
        password=body.password,
    )
    return ApiResponse(
        success=True,
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump(),
    )


@router.post("/refresh", summary="Refresh access token")
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    access_token, refresh_token = await service.refresh_tokens(
        refresh_token=body.refresh_token,
    )
    return ApiResponse(
        success=True,
        data=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump(),
    )


@router.get("/me", summary="Get current user profile")
async def get_me(
    user: User = Depends(get_current_user),
) -> ApiResponse:
    return ApiResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(mode="json"),
    )


@router.get("/users", summary="List users (role hierarchy restricted)")
async def list_users(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    users = await service.list_all()
    admin_level = ROLE_LEVELS.get(admin.role, 0)
    visible_users = [
        u for u in users
        if ROLE_LEVELS.get(u.role, 0) <= admin_level
    ]
    return ApiResponse(
        success=True,
        data=[UserResponse.model_validate(u).model_dump(mode="json") for u in visible_users],
    )


@router.put("/users/{user_id}/role", summary="Update user role (admin only)")
async def update_role(
    user_id: uuid.UUID,
    body: UpdateRoleRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    target_user = await service.get(user_id)
    admin_level = ROLE_LEVELS.get(admin.role, 0)
    target_level = ROLE_LEVELS.get(target_user.role, 0)
    new_role = UserRole[body.role]
    new_level = ROLE_LEVELS.get(new_role, 0)

    if target_level > admin_level or new_level > admin_level:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify a user or assign a role higher than your own"
        )

    user = await service.update_role(user_id, new_role)
    return ApiResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(mode="json"),
    )


@router.delete("/users/{user_id}", summary="Deactivate user (admin only)")
async def deactivate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    target_user = await service.get(user_id)
    admin_level = ROLE_LEVELS.get(admin.role, 0)
    target_level = ROLE_LEVELS.get(target_user.role, 0)

    if target_level > admin_level:
        raise HTTPException(
            status_code=403,
            detail="Cannot deactivate a user with a role higher than your own"
        )

    user = await service.deactivate(user_id)
    return ApiResponse(
        success=True,
        data=UserResponse.model_validate(user).model_dump(mode="json"),
    )


@router.post("/change-password", summary="Change own password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    await service.change_password(
        user_id=user.id,
        current_password=body.current_password,
        new_password=body.new_password,
    )
    return ApiResponse(success=True, data={"message": "Password changed"})


@router.post("/impersonate/{user_id}", summary="Impersonate a user (super admin only)")
async def impersonate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiResponse:
    service = UserService(session)
    access_token, refresh_token, target = await service.impersonate(
        target_user_id=user_id,
        impersonator_id=admin.id,
    )
    return ApiResponse(
        success=True,
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "target_user": UserResponse.model_validate(target).model_dump(mode="json"),
        },
    )
