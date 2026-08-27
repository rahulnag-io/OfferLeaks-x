"""Integration tests for Version 4's credit paywall around `POST /analyses`.

Companion to `test_analyses_endpoints.py` -- kept in a separate module so
the credit-specific scenarios (insufficient balance, balance decrement,
race safety, client-supplied-cost rejection) are easy to find together.
"""

import asyncio

from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.providers.factory import get_malware_scan_provider, get_storage_provider
from offerleaks.providers.malware_scan import ScanResult
from offerleaks.repositories.credit_repository import CreditRepository
from offerleaks.repositories.user_repository import UserRepository

from .fakes import FakeMalwareScanProvider, FakeStorageProvider

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _install_fake_providers(app):
    storage = FakeStorageProvider()
    scanner = FakeMalwareScanProvider(result=ScanResult(is_clean=True))
    app.dependency_overrides[get_storage_provider] = lambda: storage
    app.dependency_overrides[get_malware_scan_provider] = lambda: scanner
    return storage, scanner


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "correcthorsebattery", "full_name": "Test"},
    )
    return response.json()["access_token"]


async def _set_balance(email: str, balance: int) -> None:
    async with async_session_factory() as db:
        user = await UserRepository(db).get_by_email(email)
        assert user is not None
        repo = CreditRepository(db)
        current = await repo.get_balance(user.id)
        assert current is not None
        # Drive the balance to the exact target via the same atomic ops
        # the service uses, rather than writing to the row directly.
        if balance < current.balance:
            await repo.try_consume(user_id=user.id, amount=current.balance - balance)
        elif balance > current.balance:
            await repo.add_balance(user_id=user.id, amount=balance - current.balance)
        await db.commit()


def _upload(client, token: str):
    return client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )


async def test_create_analysis_succeeds_with_sufficient_credits(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "sufficient@example.com")

    response = await _upload(client, token)

    assert response.status_code == 202


async def test_create_analysis_charges_one_credit(app, client):
    _install_fake_providers(app)
    email = "charged@example.com"
    token = await _register_and_get_token(client, email)
    settings = get_settings()

    await _upload(client, token)

    balance_response = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert (
        balance_response.json()["balance"]
        == settings.credit_initial_grant - settings.credit_cost_per_analysis
    )


async def test_create_analysis_rejects_with_insufficient_credits(app, client):
    _install_fake_providers(app)
    email = "broke@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 0)

    response = await _upload(client, token)

    assert response.status_code == 402


async def test_create_analysis_succeeds_at_exact_balance(app, client):
    _install_fake_providers(app)
    email = "exact@example.com"
    token = await _register_and_get_token(client, email)
    settings = get_settings()
    await _set_balance(email, settings.credit_cost_per_analysis)

    response = await _upload(client, token)

    assert response.status_code == 202
    balance_response = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert balance_response.json()["balance"] == 0


async def test_create_analysis_cannot_be_started_twice_on_one_credit_concurrently(app, client):
    """User has exactly 1 credit. Two concurrent upload requests race for
    it -- exactly one must be accepted."""
    _install_fake_providers(app)
    email = "race@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 1)

    responses = await asyncio.gather(
        _upload(client, token), _upload(client, token), _upload(client, token)
    )
    status_codes = [r.status_code for r in responses]

    assert status_codes.count(202) == 1
    assert status_codes.count(402) == 2

    balance_response = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert balance_response.json()["balance"] == 0  # never negative


async def test_client_cannot_influence_credit_cost_via_request_body(app, client):
    """The upload endpoint only accepts a `file` field -- there is no
    request field for cost/credits/plan for a client to try to set. This
    test documents that guarantee: extra form fields are simply ignored,
    the server-side configured cost is what's charged."""
    _install_fake_providers(app)
    email = "no-override@example.com"
    token = await _register_and_get_token(client, email)
    settings = get_settings()

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
        data={"credit_cost": "0", "credits": "0", "paid": "true"},
    )

    assert response.status_code == 202
    balance_response = await client.get(
        "/credits/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert (
        balance_response.json()["balance"]
        == settings.credit_initial_grant - settings.credit_cost_per_analysis
    )
