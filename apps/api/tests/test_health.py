"""Tests for the health check endpoints."""

import pytest


@pytest.mark.anyio
async def test_health_liveness(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "OfferLeaks API"


@pytest.mark.anyio
async def test_health_dependencies(client):
    response = await client.get("/health/dependencies")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] in ("ok", "error")
    assert body["redis"] in ("ok", "error")
