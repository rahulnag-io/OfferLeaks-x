"""Authentication endpoints.

Routers stay thin: request/response translation and status-code mapping
only, all business logic lives in `AuthService` (architecture.md §0.3).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.core.db import get_db_session
from offerleaks.core.rate_limit import rate_limit
from offerleaks.core.redis import get_redis
from offerleaks.models.user import User
from offerleaks.schemas.auth import (
    GoogleOAuthUpsertRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from offerleaks.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    TokenPair,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_auth_rate_limit = rate_limit(key="auth", max_attempts=10, window_seconds=60)


def _get_auth_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> AuthService:
    return AuthService(db, redis)


async def _verify_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    """Guards server-to-server-only endpoints (the Google OAuth upsert).

    This endpoint creates/logs into an account purely from an asserted
    identity with no password check, so it must never be reachable from a
    browser -- only from the Next.js server, which holds this secret.
    """
    if x_internal_secret is None or x_internal_secret != settings.internal_api_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _to_token_response(user: User, tokens: TokenPair) -> TokenResponse:
    return TokenResponse(
        user=UserResponse.model_validate(user),
        access_token=tokens.access_token,
        access_token_expires_at=tokens.access_token_expires_at,
        refresh_token=tokens.refresh_token,
        refresh_token_expires_at=tokens.refresh_token_expires_at,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(_get_auth_service)],
    _: Annotated[None, Depends(_auth_rate_limit)],
) -> TokenResponse:
    try:
        user = await auth_service.register(
            email=body.email, password=body.password, full_name=body.full_name
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists"
        ) from exc

    tokens = await auth_service.issue_tokens(user)
    return _to_token_response(user, tokens)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    auth_service: Annotated[AuthService, Depends(_get_auth_service)],
    _: Annotated[None, Depends(_auth_rate_limit)],
) -> TokenResponse:
    try:
        user = await auth_service.authenticate(email=body.email, password=body.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        ) from exc

    tokens = await auth_service.issue_tokens(user)
    return _to_token_response(user, tokens)


@router.post("/oauth/google", response_model=TokenResponse)
async def google_oauth_upsert(
    body: GoogleOAuthUpsertRequest,
    auth_service: Annotated[AuthService, Depends(_get_auth_service)],
    _secret: Annotated[None, Depends(_verify_internal_secret)],
) -> TokenResponse:
    user = await auth_service.upsert_google_user(
        subject=body.subject, email=body.email, full_name=body.full_name
    )
    tokens = await auth_service.issue_tokens(user)
    return _to_token_response(user, tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(_get_auth_service)],
) -> TokenResponse:
    try:
        user, tokens = await auth_service.refresh(body.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token"
        ) from exc

    return _to_token_response(user, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    auth_service: Annotated[AuthService, Depends(_get_auth_service)],
) -> None:
    await auth_service.logout(body.refresh_token)
