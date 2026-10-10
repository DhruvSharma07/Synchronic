"""
Pydantic request/response models for the auth and user endpoints.
"""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: str
    avatar_url: str | None = None


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_url: str | None = None


# --- Documents ---------------------------------------------------------------
# Only 'editor' and 'viewer' can be granted in the MVP; 'commenter' arrives with
# comments (V1) and 'owner' is only ever set via transfer-ownership.
GrantableRole = Literal["editor", "viewer"]


class DocumentCreate(BaseModel):
    title: str = Field(default="Untitled document", min_length=1, max_length=200)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_link_shareable: bool | None = None
    link_share_role: GrantableRole | None = None


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    owner_id: uuid.UUID
    role: str  # the caller's effective role on this document
    is_link_shareable: bool
    link_share_role: str
    created_at: datetime
    updated_at: datetime


class PermissionGrant(BaseModel):
    email: EmailStr | None = None
    user_id: uuid.UUID | None = None
    role: GrantableRole

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if (self.email is None) == (self.user_id is None):
            raise ValueError("Provide exactly one of email or user_id")
        return self


class PermissionEntry(BaseModel):
    user: UserResponse
    role: str
    granted_at: datetime


class TransferOwnershipRequest(BaseModel):
    user_id: uuid.UUID
