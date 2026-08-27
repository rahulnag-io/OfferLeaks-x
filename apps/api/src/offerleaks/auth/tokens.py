"""JWT access & refresh token issuance and verification.

The API mints and verifies these tokens itself -- it never trusts a token
it didn't sign (architecture.md §0.13: "FastAPI does not trust NextAuth's
session cookie directly"). Whatever mechanism the frontend uses to get a
token to the browser is irrelevant here; this module only cares about the
token string's signature, issuer, expiry, and type.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import jwt
from jwt import InvalidTokenError

from offerleaks.core.config import get_settings
from offerleaks.models.user import Role


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Raised for any invalid, expired, or malformed token."""


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: uuid.UUID
    role: Role
    token_type: TokenType
    jti: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    jti: str
    expires_at: datetime


def _create_token(
    user_id: uuid.UUID, role: Role, token_type: TokenType, ttl: timedelta
) -> IssuedToken:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + ttl
    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": token_type.value,
        "iat": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "jti": jti,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return IssuedToken(token=token, jti=jti, expires_at=expires_at)


def create_access_token(user_id: uuid.UUID, role: Role) -> IssuedToken:
    settings = get_settings()
    return _create_token(
        user_id, role, TokenType.ACCESS, timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: uuid.UUID, role: Role) -> IssuedToken:
    settings = get_settings()
    return _create_token(
        user_id, role, TokenType.REFRESH, timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str, *, expected_type: TokenType) -> TokenPayload:
    """Verify signature, issuer, and expiry, then check the token type.

    Raises `TokenError` for anything wrong with the token -- callers
    shouldn't need to know or care whether that was a bad signature, an
    expired token, or a refresh token presented where an access token was
    expected.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "jti", "type"]},
        )
    except InvalidTokenError as exc:
        raise TokenError(str(exc)) from exc

    if raw.get("type") != expected_type.value:
        raise TokenError(f"expected a {expected_type.value} token")

    try:
        role = Role(raw["role"])
        user_id = uuid.UUID(raw["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed token payload") from exc

    return TokenPayload(
        user_id=user_id,
        role=role,
        token_type=expected_type,
        jti=raw["jti"],
        expires_at=datetime.fromtimestamp(raw["exp"], tz=UTC),
    )
