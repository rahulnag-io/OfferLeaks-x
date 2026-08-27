"""FastAPI dependencies for authentication & RBAC.

`get_current_user` is the single place that turns a bearer token into a
loaded `User` row -- routers never decode tokens themselves. `require_roles`
is the RBAC scaffold referenced in architecture.md §0.11: the permission-check
plumbing exists from Version 2 even though every route today only needs
`Role.USER`. Version 8's moderation endpoints add `require_roles(Role.ADMIN,
Role.MODERATOR)` without touching this module.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.tokens import TokenError, TokenType, decode_token
from offerleaks.core.db import get_db_session
from offerleaks.models.user import Role, User
from offerleaks.repositories.user_repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    db: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise _CREDENTIALS_EXCEPTION from exc

    user = await UserRepository(db).get_by_id(payload.user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXCEPTION

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: Role) -> Callable[..., Coroutine[Any, Any, User]]:
    """Build a dependency that requires the current user to hold one of `allowed_roles`."""

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user

    return _dependency
