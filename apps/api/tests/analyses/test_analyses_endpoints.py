"""Integration tests for `/analyses` against the real app, DB, and Redis.

Follows the same convention as `test_auth_endpoints.py`: real Postgres and
Redis, nothing mocked there. What *is* faked is the external-provider
boundary (storage/malware-scan) via `app.dependency_overrides` -- exactly
the seam architecture.md §0.6/§0.13 put there so this doesn't need a real
S3 bucket or ClamAV daemon to verify the upload flow end-to-end.
"""

from offerleaks.providers.factory import get_malware_scan_provider, get_storage_provider
from offerleaks.providers.malware_scan import ScanResult

from .fakes import FakeMalwareScanProvider, FakeStorageProvider

REGISTER_BODY = {
    "email": "alice@example.com",
    "password": "correcthorsebattery",
    "full_name": "Alice",
}

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _install_fake_providers(app, *, scan_result: ScanResult | None = None, scan_unavailable=False):
    storage = FakeStorageProvider()
    scanner = FakeMalwareScanProvider(
        result=scan_result or ScanResult(is_clean=True),
        raise_unavailable=scan_unavailable,
    )
    app.dependency_overrides[get_storage_provider] = lambda: storage
    app.dependency_overrides[get_malware_scan_provider] = lambda: scanner
    return storage, scanner


async def _register_and_get_token(client) -> str:
    response = await client.post("/auth/register", json=REGISTER_BODY)
    return response.json()["access_token"]


async def test_create_analysis_requires_authentication(app, client):
    _install_fake_providers(app)
    response = await client.post(
        "/analyses", files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")}
    )
    assert response.status_code == 401


async def test_create_analysis_returns_202_pending(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["file_name"] == "offer.pdf"
    assert body["verdict"] is None
    assert body["prompt_version"]


async def test_create_analysis_stores_the_original_file(app, client):
    storage, _ = _install_fake_providers(app)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.json()["id"]
    assert len(storage.objects) == 1
    assert next(iter(storage.objects.values())) == PDF_BYTES


async def test_create_analysis_rejects_disallowed_file_type(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.exe", b"MZ\x90\x00" + b"\x00" * 20, "application/octet-stream")},
    )

    assert response.status_code == 415


async def test_create_analysis_rejects_oversized_file(app, client):
    from offerleaks.core.config import get_settings

    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    # A well-formed PDF (valid magic bytes) padded past the configured
    # size cap -- isolates the size check from the MIME-sniffing check
    # rather than mutating the process-wide cached Settings singleton.
    oversized = PDF_BYTES + b"\x00" * get_settings().max_upload_size_bytes

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", oversized, "application/pdf")},
    )

    assert response.status_code == 413


async def test_create_analysis_rejects_malware(app, client):
    _install_fake_providers(
        app, scan_result=ScanResult(is_clean=False, threat_name="Eicar-Test-Signature")
    )
    token = await _register_and_get_token(client)

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 422


async def test_create_analysis_fails_closed_when_scanner_unavailable(app, client):
    _install_fake_providers(app, scan_unavailable=True)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 503


async def test_get_analysis_requires_authentication(app, client):
    _install_fake_providers(app)
    response = await client.get("/analyses/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 401


async def test_get_analysis_returns_404_for_unknown_id(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    response = await client.get(
        "/analyses/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_get_analysis_returns_404_for_malformed_id(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    response = await client.get(
        "/analyses/not-a-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_get_analysis_returns_the_pending_analysis_to_its_owner(app, client):
    _install_fake_providers(app)
    token = await _register_and_get_token(client)

    create = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )
    analysis_id = create.json()["id"]

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == analysis_id
    assert response.json()["status"] == "pending"


async def test_get_analysis_is_not_visible_to_another_user(app, client):
    _install_fake_providers(app)
    owner_token = await _register_and_get_token(client)

    create = await client.post(
        "/analyses",
        headers={"Authorization": f"Bearer {owner_token}"},
        files={"file": ("offer.pdf", PDF_BYTES, "application/pdf")},
    )
    analysis_id = create.json()["id"]

    other_register = await client.post(
        "/auth/register",
        json={"email": "mallory@example.com", "password": "correcthorsebattery"},
    )
    other_token = other_register.json()["access_token"]

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {other_token}"}
    )

    assert response.status_code == 404
