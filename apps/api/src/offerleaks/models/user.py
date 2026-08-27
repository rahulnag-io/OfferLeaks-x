"""User model.

RBAC scaffold (architecture.md §0.11): the `Role` enum and the column exist
from Version 2 even though only `USER` is reachable through any endpoint
right now. `ADMIN` and `MODERATOR` are wired into the permission-check
plumbing (see `offerleaks.auth.dependencies.require_roles`) so the
moderation queue in Version 8 is additive, not a retrofit.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class Role(enum.StrEnum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class OAuthProvider(enum.StrEnum):
    GOOGLE = "google"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Nullable: OAuth-only users (e.g. Google sign-in) never set a password.
    # A user who registered with a password can still later link Google;
    # that upsert path never overwrites an existing hashed_password.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    oauth_provider: Mapped[OAuthProvider | None] = mapped_column(
        Enum(
            OAuthProvider,
            name="oauth_provider",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    oauth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # values_callable: store the lowercase string *values* ("user", not
    # "USER") so the DB representation matches the API/JSON representation
    # of the enum -- avoids a silent name/value mismatch between Python's
    # default SQLAlchemy Enum behavior (which persists member .name) and
    # everything else in the system that speaks Role.value.
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="user_role",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=Role.USER,
        server_default=Role.USER.value,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
