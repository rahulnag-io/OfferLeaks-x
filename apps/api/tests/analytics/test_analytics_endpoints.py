"""Endpoint-level test for `GET /analytics/me` (M8): free for every plan,
no auth means no access.
"""





async def _register(client, email: str) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "correcthorsebattery", "full_name": "Test User"},
    )
    return response.json()["access_token"]


async def test_free_user_can_access_personal_analytics(app, client):
    token = await _register(client, "free-analytics@example.com")

    response = await client.get(
        "/analytics/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_analyses"] == 0
    assert body["average_risk_score"] is None


async def test_analytics_requires_authentication(app, client):
    response = await client.get("/analytics/me")
    assert response.status_code == 401
