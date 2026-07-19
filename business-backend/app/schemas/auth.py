from datetime import datetime
import uuid
import enum

from pydantic import BaseModel, Field, EmailStr


class UserRoleEnum(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    OPERATOR = "OPERATOR"


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100, examples=["john"])
    email: EmailStr = Field(..., examples=["john@warehouse.com"])
    password: str = Field(..., min_length=8, max_length=128, examples=["securePass123"])
    role: UserRoleEnum = Field(UserRoleEnum.OPERATOR, examples=["OPERATOR"])


class LoginRequest(BaseModel):
    username: str = Field(..., examples=["john"])
    password: str = Field(..., examples=["securePass123"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
