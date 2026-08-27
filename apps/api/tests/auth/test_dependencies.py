"""Tests for the RBAC dependency scaffold.

No endpoint uses `require_roles` with anything but `Role.USER` yet
(Version 8 is the first real consumer), so this exercises the dependency
factory directly rather than through a router.
"""

import uuid

import pytest
from fastapi import HTTPException

from offerleaks.auth.dependencies import require_roles
from offerleaks.models.user import Role, User


def _make_user(role: Role) -> User:
    return User(id=uuid.uuid4(), email="test@example.com", role=role)


async def test_require_roles_allows_matching_role():
    dependency = require_roles(Role.ADMIN, Role.MODERATOR)
    user = _make_user(Role.ADMIN)

    result = await dependency(user)

    assert result is user


async def test_require_roles_rejects_non_matching_role():
    dependency = require_roles(Role.ADMIN)
    user = _make_user(Role.USER)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(user)

    assert exc_info.value.status_code == 403
