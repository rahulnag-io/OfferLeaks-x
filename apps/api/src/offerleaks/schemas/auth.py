"""Request/response schemas for the `/auth` and `/users` routers."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from offerleaks.models.user import Role


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: Role
    is_active: bool
    email_verified: bool
    created_at: datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    # Argon2 hashes the whole input regardless of length, so there's no
    # bcrypt-style 72-byte cap to enforce -- just a sane minimum.
    password: str = Field(min_length=8, max_length=256)
    full_name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleOAuthUpsertRequest(BaseModel):
    """Called server-to-server by the Next.js app after it verifies the
    Google identity itself -- this endpoint trusts the caller's assertion
    of `subject`/`email`, so it's gated by `internal_api_secret`, never
    reachable from a browser.
    """

    subject: str = Field(min_length=1)
    email: EmailStr
    full_name: str | None = None


class TokenResponse(BaseModel):
    user: UserResponse
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    token_type: str = "bearer"
