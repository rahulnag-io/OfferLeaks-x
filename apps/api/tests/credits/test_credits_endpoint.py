"""Integration tests for `/credits` against the real app, DB, and Redis."""

from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.repositories.credit_repository import CreditRepository
from offerleaks.repositories.user_repository import UserRepository

REGISTER_BODY = {
    "email": "alice@example.com",
    "password": "correcthorsebattery",
    "full_name": "Alice",
}


async def _register_and_get_token(client, email: str = REGISTER_BODY["email"]) -> str:
    body = {**REGISTER_BODY, "email": email}
    response = await client.post("/auth/register", json=body)
    return response.json()["access_token"]


async def test_get_credits_requires_authentication(client):
    response = await client.get("/credits/me")
    assert response.status_code == 401


async def test_get_credits_returns_initial_grant_after_registration(client):
    token = await _register_and_get_token(client)

    response = await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    settings = get_settings()
    assert body["balance"] == settings.credit_initial_grant
    assert body["cost_per_analysis"] == settings.credit_cost_per_analysis


async def test_get_credits_is_scoped_to_the_authenticated_user(client):
    """There is no `{user_id}` in the URL to manipulate -- but as a
    behavioral check, two different users see two independent balances."""
    token_a = await _register_and_get_token(client, email="a@example.com")
    token_b = await _register_and_get_token(client, email="b@example.com")

    response_a = await client.get("/credits/me", headers={"Authorization": f"Bearer {token_a}"})
    response_b = await client.get("/credits/me", headers={"Authorization": f"Bearer {token_b}"})

    settings = get_settings()
    assert response_a.json()["balance"] == settings.credit_initial_grant
    assert response_b.json()["balance"] == settings.credit_initial_grant

    # Confirm this is actually two distinct balance rows, not a fluke of
    # both starting at the same number: spend one of them and re-check.
    async with async_session_factory() as db:
        user_a = await UserRepository(db).get_by_email("a@example.com")
        assert user_a is not None
        await CreditRepository(db).try_consume(user_id=user_a.id, amount=1)
        await db.commit()

    response_a_after = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token_a}"}
    )
    response_b_after = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert response_a_after.json()["balance"] == settings.credit_initial_grant - 1
    assert response_b_after.json()["balance"] == settings.credit_initial_grant  # untouched
