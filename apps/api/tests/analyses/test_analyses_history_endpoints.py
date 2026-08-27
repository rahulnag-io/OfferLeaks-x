"""Integration tests for Version 5's dashboard/history endpoints:
`GET /analyses` (list) and `POST /analyses/{id}/recheck`.

Companion to `test_analyses_endpoints.py`/`test_analysis_credits.py` --
kept separate so the Version 5-specific scenarios (pagination, status
filtering, ownership on history, re-check pricing/concurrency) are easy to
find together, following the same real-Postgres-and-Redis convention as
the rest of the analysis test suite.
"""

import asyncio

from offerleaks import worker
from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.providers.factory import get_malware_scan_provider, get_storage_provider
from offerleaks.providers.malware_scan import ScanResult
from offerleaks.repositories.credit_repository import CreditRepository
from offerleaks.repositories.user_repository import UserRepository

from .fakes import FakeAIProvider, FakeMalwareScanProvider, FakeOCRProvider, FakeStorageProvider

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _install_fake_providers(app, storage: FakeStorageProvider | None = None):
    storage = storage or FakeStorageProvider()
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
        if balance < current.balance:
            await repo.try_consume(user_id=user.id, amount=current.balance - balance)
        elif balance > current.balance:
            await repo.add_balance(user_id=user.id, amount=balance - current.balance)
        await db.commit()


def _upload(client, token: str, file_name: str = "offer.pdf"):
    return client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (file_name, PDF_BYTES, "application/pdf")},
    )


async def _complete(analysis_id: str, monkeypatch, storage: FakeStorageProvider) -> None:
    """Drives a PENDING analysis to COMPLETE via the real worker pipeline,
    with fake OCR/AI providers -- same pattern as `test_analysis_worker.py`.
    """
    import uuid as uuid_mod

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())
    await worker._process_analysis(uuid_mod.UUID(analysis_id))


# --- GET /analyses (list) ---


async def test_list_analyses_requires_authentication(app, client):
    _install_fake_providers(app)
    response = await client.get("/analyses")
    assert response.status_code == 401


async def test_list_analyses_returns_empty_for_new_user(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "empty@example.com")

    response = await client.get("/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_analyses_returns_newest_first(app, client):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client, "history@example.com")

    first = await _upload(client, token, "first.pdf")
    second = await _upload(client, token, "second.pdf")

    response = await client.get("/analyses", headers={"Authorization": f"Bearer {token}"})

    body = response.json()
    assert body["total"] == 2
    assert [item["file_name"] for item in body["items"]] == ["second.pdf", "first.pdf"]
    assert body["items"][0]["id"] == second.json()["id"]
    assert body["items"][1]["id"] == first.json()["id"]


async def test_list_analyses_only_shows_the_caller_owned_analyses(app, client):
    _install_fake_providers(app)
    owner_token = await _register_and_get_token(client, "owner@example.com")
    other_token = await _register_and_get_token(client, "other@example.com")

    await _upload(client, owner_token)

    response = await client.get("/analyses", headers={"Authorization": f"Bearer {other_token}"})

    assert response.json()["total"] == 0


async def test_list_analyses_paginates(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "paginate@example.com")
    await _set_balance("paginate@example.com", 10)

    for i in range(5):
        await _upload(client, token, f"offer-{i}.pdf")

    page1 = await client.get(
        "/analyses?limit=2&offset=0", headers={"Authorization": f"Bearer {token}"}
    )
    page2 = await client.get(
        "/analyses?limit=2&offset=2", headers={"Authorization": f"Bearer {token}"}
    )

    assert page1.json()["total"] == 5
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 2
    page1_ids = {item["id"] for item in page1.json()["items"]}
    page2_ids = {item["id"] for item in page2.json()["items"]}
    assert page1_ids.isdisjoint(page2_ids)


async def test_list_analyses_rejects_limit_above_max(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "limit@example.com")

    response = await client.get(
        "/analyses?limit=999", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 422


async def test_list_analyses_filters_by_status(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client, "filter@example.com")
    await _set_balance("filter@example.com", 10)

    pending = await _upload(client, token, "pending.pdf")
    completed = await _upload(client, token, "completed.pdf")
    await _complete(completed.json()["id"], monkeypatch, storage)

    response = await client.get(
        "/analyses?status=complete", headers={"Authorization": f"Bearer {token}"}
    )

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == completed.json()["id"]
    assert body["items"][0]["id"] != pending.json()["id"]


async def test_list_analyses_reports_credit_cost_and_verdict(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client, "cost@example.com")

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)

    response = await client.get("/analyses", headers={"Authorization": f"Bearer {token}"})

    item = response.json()["items"][0]
    assert item["credit_cost"] == get_settings().credit_cost_per_analysis
    assert item["verdict"] is not None
    assert item["source_analysis_id"] is None


# --- POST /analyses/{id}/recheck ---


async def test_recheck_requires_authentication(app, client):
    _install_fake_providers(app)
    response = await client.post("/analyses/00000000-0000-0000-0000-000000000000/recheck")
    assert response.status_code == 401


async def test_recheck_returns_404_for_unknown_id(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "recheck404@example.com")

    response = await client.post(
        "/analyses/00000000-0000-0000-0000-000000000000/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_recheck_returns_404_for_another_users_analysis(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    owner_token = await _register_and_get_token(client, "recheck-owner@example.com")
    other_token = await _register_and_get_token(client, "recheck-other@example.com")

    created = await _upload(client, owner_token)
    await _complete(created.json()["id"], monkeypatch, storage)

    response = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404


async def test_recheck_returns_409_while_source_is_still_processing(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client, "recheck-pending@example.com")

    created = await _upload(client, token)  # left PENDING -- worker never run

    response = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_recheck_is_free_the_first_time_prompt_version_is_unchanged(
    app, client, monkeypatch
):
    storage, _ = _install_fake_providers(app)
    email = "recheck-free@example.com"
    token = await _register_and_get_token(client, email)

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)

    balance_before = (
        await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["balance"]

    response = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["source_analysis_id"] == created.json()["id"]
    assert body["credit_cost"] == 0
    assert body["file_name"] == created.json()["file_name"]

    balance_after = (
        await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["balance"]
    assert balance_after == balance_before


async def test_recheck_charges_full_price_the_second_time_even_if_prompt_unchanged(
    app, client, monkeypatch
):
    storage, _ = _install_fake_providers(app)
    email = "recheck-cap@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 10)

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)
    source_id = created.json()["id"]

    first_recheck = await client.post(
        f"/analyses/{source_id}/recheck", headers={"Authorization": f"Bearer {token}"}
    )
    assert first_recheck.json()["credit_cost"] == 0

    balance_before_second = (
        await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["balance"]

    second_recheck = await client.post(
        f"/analyses/{source_id}/recheck", headers={"Authorization": f"Bearer {token}"}
    )

    assert second_recheck.status_code == 202
    assert second_recheck.json()["credit_cost"] == get_settings().credit_cost_per_analysis

    balance_after_second = (
        await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["balance"]
    assert balance_after_second == balance_before_second - get_settings().credit_cost_per_analysis


async def test_recheck_charges_full_price_when_prompt_version_changed(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    email = "recheck-newprompt@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 10)

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)

    # Simulate a prompt-version bump between the original run and the
    # re-check -- patch the module-level settings the service reads.
    from offerleaks.services import analysis_service as analysis_service_module

    original_settings = analysis_service_module.get_settings()
    monkeypatch.setattr(
        analysis_service_module,
        "get_settings",
        lambda: original_settings.model_copy(update={"ai_prompt_version": "offer_letter_v2"}),
    )

    response = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    assert response.json()["credit_cost"] == get_settings().credit_cost_per_analysis
    assert response.json()["prompt_version"] == "offer_letter_v2"


async def test_recheck_returns_402_when_insufficient_credits_for_a_charged_recheck(
    app, client, monkeypatch
):
    storage, _ = _install_fake_providers(app)
    email = "recheck-poor@example.com"
    token = await _register_and_get_token(client, email)

    created = await _upload(client, token)  # spends the signup grant down
    await _complete(created.json()["id"], monkeypatch, storage)
    await _set_balance(email, 0)

    # First (free) re-check still succeeds even at 0 balance.
    first = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 202
    assert first.json()["credit_cost"] == 0

    # Second re-check would be charged, but the balance is 0.
    second = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 402


async def test_concurrent_rechecks_only_grant_the_free_slot_once(app, client, monkeypatch):
    """Closes the race this pricing rule would otherwise have: two
    concurrent re-check requests for the same source analysis must not
    both land the one free re-check -- exactly the scenario
    `AnalysisRepository.try_claim_free_recheck`'s atomic UPDATE exists for.
    """
    storage, _ = _install_fake_providers(app)
    email = "recheck-race@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 10)

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)
    source_id = created.json()["id"]

    responses = await asyncio.gather(
        *[
            client.post(
                f"/analyses/{source_id}/recheck", headers={"Authorization": f"Bearer {token}"}
            )
            for _ in range(5)
        ]
    )

    assert all(r.status_code == 202 for r in responses)
    free_count = sum(1 for r in responses if r.json()["credit_cost"] == 0)
    charged_count = sum(
        1 for r in responses if r.json()["credit_cost"] == get_settings().credit_cost_per_analysis
    )
    assert free_count == 1
    assert charged_count == 4

    balance = (
        await client.get("/credits/me", headers={"Authorization": f"Bearer {token}"})
    ).json()["balance"]
    # Started at 10, the original upload spent 1 (-> 9), then 4 of the 5
    # concurrent re-checks were charged (-> 9 - 4).
    cost = get_settings().credit_cost_per_analysis
    assert balance == 10 - cost - 4 * cost


async def test_recheck_reuses_the_stored_file_without_a_new_upload(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client, "recheck-storage@example.com")

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)
    assert len(storage.objects) == 1  # only the original upload

    await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    # No new object written to storage -- the re-check reused the
    # existing `file_storage_key` rather than re-uploading.
    assert len(storage.objects) == 1


async def test_get_analysis_includes_source_analysis_id_and_credit_cost(app, client, monkeypatch):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client, "recheck-detail@example.com")

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)

    recheck = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )
    recheck_id = recheck.json()["id"]

    detail = await client.get(
        f"/analyses/{recheck_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert detail.status_code == 200
    assert detail.json()["source_analysis_id"] == created.json()["id"]
    assert detail.json()["credit_cost"] == 0


async def test_recheck_of_a_recheck_still_requires_terminal_state(app, client, monkeypatch):
    """A re-check that's still PENDING (worker not yet run) can't itself
    be re-checked -- the terminal-state guard applies uniformly regardless
    of whether the analysis being re-checked is itself an original upload
    or an earlier re-check."""
    storage, _ = _install_fake_providers(app)
    email = "recheck-of-recheck@example.com"
    token = await _register_and_get_token(client, email)
    await _set_balance(email, 10)

    created = await _upload(client, token)
    await _complete(created.json()["id"], monkeypatch, storage)

    first_recheck = await client.post(
        f"/analyses/{created.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Deliberately not driven to COMPLETE via `_complete` -- still PENDING.

    response = await client.post(
        f"/analyses/{first_recheck.json()['id']}/recheck",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
