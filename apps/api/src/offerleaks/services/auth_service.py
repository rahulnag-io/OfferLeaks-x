"""Authentication business logic.

Orchestrates the repository + `auth/` primitives; routers call this, never
the repository or `auth/` modules directly (architecture.md §0.3).
"""

from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.security import hash_password, needs_rehash, verify_password
from offerleaks.auth.sessions import (
    is_refresh_session_valid,
    revoke_refresh_session,
    store_refresh_session,
)
from offerleaks.auth.tokens import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from offerleaks.models.user import OAuthProvider, User
from offerleaks.repositories.user_repository import UserRepository
from offerleaks.services.credit_service import CreditService


class AuthError(Exception):
    """Base class for all auth-service failures. Routers map this to 4xx."""


class InvalidCredentialsError(AuthError):
    pass


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidRefreshTokenError(AuthError):
    pass


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self._db = db
        self._redis = redis
        self._users = UserRepository(db)
        self._credits = CreditService(db)

    async def register(self, *, email: str, password: str, full_name: str | None) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(email)

        user = await self._users.create(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
        )
        # Same transaction as user creation (committed together below) --
        # see CreditService.grant_initial_credits' docstring for why.
        await self._credits.grant_initial_credits(user.id)
        await self._db.commit()
        return user

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._users.get_by_email(email)
        if user is None or user.hashed_password is None:
            # Same error for "no such user" and "wrong password" -- don't
            # let the endpoint's response shape leak which emails are
            # registered.
            raise InvalidCredentialsError

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError

        if not user.is_active:
            raise InvalidCredentialsError

        if needs_rehash(user.hashed_password):
            await self._users.update_password_hash(user, hash_password(password))
            await self._db.commit()

        return user

    async def upsert_google_user(self, *, subject: str, email: str, full_name: str | None) -> User:
        """Find-or-create a user from a Google identity.

        Matches on the OAuth identity first, then falls back to matching
        an existing password-registered account by email (so a user who
        signed up with a password and later clicks "Sign in with Google"
        lands on the same account instead of a silent duplicate) and links
        the identity onto it.
        """
        user = await self._users.get_by_oauth_identity(OAuthProvider.GOOGLE, subject)
        if user is not None:
            return user

        user = await self._users.get_by_email(email)
        if user is not None:
            await self._users.link_oauth_identity(
                user, provider=OAuthProvider.GOOGLE, subject=subject
            )
            await self._db.commit()
            return user

        user = await self._users.create(
            email=email,
            full_name=full_name,
            oauth_provider=OAuthProvider.GOOGLE,
            oauth_subject=subject,
            email_verified=True,  # Google has already verified this address.
        )
        await self._credits.grant_initial_credits(user.id)
        await self._db.commit()
        return user

    async def issue_tokens(self, user: User) -> TokenPair:
        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token(user.id, user.role)
        await store_refresh_session(
            self._redis, jti=refresh.jti, user_id=user.id, expires_at=refresh.expires_at
        )
        return TokenPair(
            access_token=access.token,
            access_token_expires_at=access.expires_at,
            refresh_token=refresh.token,
            refresh_token_expires_at=refresh.expires_at,
        )

    async def refresh(self, refresh_token: str) -> tuple[User, TokenPair]:
        """Rotate a refresh token: the presented one is consumed exactly once."""
        try:
            payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        except TokenError as exc:
            raise InvalidRefreshTokenError from exc

        if not await is_refresh_session_valid(
            self._redis, jti=payload.jti, user_id=payload.user_id
        ):
            raise InvalidRefreshTokenError

        user = await self._users.get_by_id(payload.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError

        # Rotation: the old refresh token is single-use.
        await revoke_refresh_session(self._redis, jti=payload.jti)
        return user, await self.issue_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
        except TokenError:
            # Already-invalid token: logout is idempotent, nothing to revoke.
            return
        await revoke_refresh_session(self._redis, jti=payload.jti)
