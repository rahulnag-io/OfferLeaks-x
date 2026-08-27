"""Data access for `User`.

Routers and services never issue SQLAlchemy queries directly against
`User` -- they go through this repository, per architecture.md §0.3's
routers -> services -> repositories layering.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.user import OAuthProvider, User


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._db.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_oauth_identity(
        self, provider: OAuthProvider, subject: str
    ) -> User | None:
        result = await self._db.execute(
            select(User).where(
                User.oauth_provider == provider,
                User.oauth_subject == subject,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        full_name: str | None = None,
        hashed_password: str | None = None,
        oauth_provider: OAuthProvider | None = None,
        oauth_subject: str | None = None,
        email_verified: bool = False,
    ) -> User:
        user = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hashed_password,
            oauth_provider=oauth_provider,
            oauth_subject=oauth_subject,
            email_verified=email_verified,
        )
        self._db.add(user)
        await self._db.flush()
        return user

    async def update_password_hash(self, user: User, hashed_password: str) -> None:
        user.hashed_password = hashed_password
        await self._db.flush()

    async def link_oauth_identity(
        self, user: User, *, provider: OAuthProvider, subject: str
    ) -> None:
        user.oauth_provider = provider
        user.oauth_subject = subject
        await self._db.flush()
