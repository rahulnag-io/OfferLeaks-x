"""Integration test for M6's monthly-analysis-quota paywall around
`POST /analyses` -- companion to `test_analysis_credits.py`, which covers
the (separate, pre-existing) credit-balance paywall. See
`EntitlementService`'s module docstring for why both gates exist
independently.
"""

from offerleaks.core.db import async_session_factory
from offerleaks.providers.factory import get_malware_scan_provider, get_storage_provider
from offerleaks.providers.malware_scan import ScanResult
from offerleaks.repositories.analysis_repository import AnalysisRepository
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


async def _give_unlimited_credits(email: str) -> None:
    """Isolates this test from the (separate, pre-existing) credit
    paywall -- a large balance so only the quota, not the balance, can
    be the reason a request is rejected."""
    async with async_session_factory() as db:
        user = await UserRepository(db).get_by_email(email)
        assert user is not None
        await CreditRepository(db).add_balance(user_id=user.id, amount=1000)
        await db.commit()


async def _seed_analyses(email: str, count: int) -> None:
    """Directly inserts `count` completed-looking analyses for the user,
    bypassing the HTTP upload path entirely. Deliberate: the real
    `POST /analyses` upload route has its own pre-existing per-user rate
    limit (5 per 5 minutes, `api/routers/analyses.py`'s
    `_upload_rate_limit`) that a tight loop of real uploads would trip
    long before reaching the free plan's monthly quota (10) -- an
    unrelated feature interaction, not something this test is meant to
    exercise. Seeding directly isolates the quota check itself, which is
    already covered at the unit level in
    `tests/entitlements/test_entitlement_service.py`; this test only
    needs to confirm the *endpoint* surfaces a 402 once the quota
    service says no.
    """
    async with async_session_factory() as db:
        user = await UserRepository(db).get_by_email(email)
        assert user is not None
        repo = AnalysisRepository(db)
        for _ in range(count):
            await repo.create(
                user_id=user.id,
                file_storage_key=f"analyses/{user.id}/seed/offer.pdf",
                file_name="offer.pdf",
                file_mime_type="application/pdf",
                file_size_bytes=len(PDF_BYTES),
                prompt_version="offer_letter_v1",
            )
        await db.commit()


async def _upload(client, token: str):
    return await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )


async def test_free_plan_user_is_blocked_after_reaching_the_monthly_limit(app, client):
    _install_fake_providers(app)
    email = "quota-test@example.com"
    token = await _register_and_get_token(client, email)
    await _give_unlimited_credits(email)

    # Seeded free-plan limit is 10 (migration b2d7e0a3c5f6).
    await _seed_analyses(email, 10)

    blocked = await _upload(client, token)
    assert blocked.status_code == 402
    assert "monthly analysis limit" in blocked.json()["detail"].lower()


async def test_free_plan_user_below_the_limit_is_not_blocked(app, client):
    _install_fake_providers(app)
    email = "quota-below-test@example.com"
    token = await _register_and_get_token(client, email)
    await _give_unlimited_credits(email)

    await _seed_analyses(email, 9)

    response = await _upload(client, token)
    assert response.status_code == 202

