"""User-facing endpoints that require authentication."""

from fastapi import APIRouter

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.schemas.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """Returns the authenticated user.

    Exists in Version 2 mainly as the smallest possible proof that the
    full loop works end-to-end: a token minted by `/auth/login` or
    `/auth/register` is independently verified here via `get_current_user`,
    with no shared state other than the JWT itself.
    """
    return UserResponse.model_validate(current_user)
