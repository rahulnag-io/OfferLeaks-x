"""Integration tests for /auth and /users against the real app, DB, and Redis."""

from offerleaks.core.config import get_settings

REGISTER_BODY = {
    "email": "alice@example.com",
    "password": "correcthorsebattery",
    "full_name": "Alice",
}


async def test_register_creates_user_and_returns_tokens(client):
    response = await client.post("/auth/register", json=REGISTER_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "user"
    assert "hashed_password" not in body["user"]
    assert body["access_token"]
    assert body["refresh_token"]


async def test_register_rejects_duplicate_email(client):
    await client.post("/auth/register", json=REGISTER_BODY)
    response = await client.post("/auth/register", json=REGISTER_BODY)

    assert response.status_code == 409


async def test_register_rejects_short_password(client):
    response = await client.post(
        "/auth/register", json={"email": "short@example.com", "password": "short"}
    )
    assert response.status_code == 422


async def test_login_with_correct_credentials_succeeds(client):
    await client.post("/auth/register", json=REGISTER_BODY)

    response = await client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "correcthorsebattery"}
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "alice@example.com"


async def test_login_with_wrong_password_fails(client):
    await client.post("/auth/register", json=REGISTER_BODY)

    response = await client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401


async def test_login_with_unknown_email_fails(client):
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )

    assert response.status_code == 401


async def test_me_requires_authentication(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_token(client):
    register = await client.post("/auth/register", json=REGISTER_BODY)
    access_token = register.json()["access_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


async def test_me_rejects_garbage_token(client):
    response = await client.get("/users/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


async def test_me_rejects_refresh_token_used_as_access_token(client):
    register = await client.post("/auth/register", json=REGISTER_BODY)
    refresh_token = register.json()["refresh_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {refresh_token}"})

    assert response.status_code == 401


async def test_refresh_issues_a_new_working_token_pair(client):
    register = await client.post("/auth/register", json=REGISTER_BODY)
    old_refresh_token = register.json()["refresh_token"]

    response = await client.post("/auth/refresh", json={"refresh_token": old_refresh_token})

    assert response.status_code == 200
    new_access_token = response.json()["access_token"]

    me = await client.get("/users/me", headers={"Authorization": f"Bearer {new_access_token}"})
    assert me.status_code == 200


async def test_refresh_token_is_single_use(client):
    register = await client.post("/auth/register", json=REGISTER_BODY)
    refresh_token = register.json()["refresh_token"]

    first = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200

    second = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401


async def test_logout_revokes_the_refresh_token(client):
    register = await client.post("/auth/register", json=REGISTER_BODY)
    refresh_token = register.json()["refresh_token"]

    logout = await client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    refresh_attempt = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_attempt.status_code == 401


async def test_google_oauth_upsert_requires_internal_secret(client):
    response = await client.post(
        "/auth/oauth/google", json={"subject": "g-1", "email": "bob@example.com"}
    )
    assert response.status_code == 403


async def test_google_oauth_upsert_creates_a_verified_user(client):
    settings = get_settings()

    response = await client.post(
        "/auth/oauth/google",
        json={"subject": "g-1", "email": "bob@example.com", "full_name": "Bob"},
        headers={"X-Internal-Secret": settings.internal_api_secret},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["email_verified"] is True


async def test_google_oauth_upsert_is_idempotent_for_the_same_identity(client):
    settings = get_settings()
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    payload = {"subject": "g-1", "email": "bob@example.com", "full_name": "Bob"}

    first = await client.post("/auth/oauth/google", json=payload, headers=headers)
    second = await client.post("/auth/oauth/google", json=payload, headers=headers)

    assert first.json()["user"]["id"] == second.json()["user"]["id"]


async def test_google_oauth_links_to_existing_password_account_by_email(client):
    await client.post("/auth/register", json=REGISTER_BODY)
    settings = get_settings()

    response = await client.post(
        "/auth/oauth/google",
        json={"subject": "g-2", "email": "alice@example.com", "full_name": "Alice"},
        headers={"X-Internal-Secret": settings.internal_api_secret},
    )

    assert response.status_code == 200
    # Password login must still work after linking a Google identity.
    login = await client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "correcthorsebattery"}
    )
    assert login.status_code == 200


async def test_auth_endpoints_are_rate_limited(client):
    settings = get_settings()
    for _ in range(settings.rate_limit_auth_attempts):
        await client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
        )

    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrong"}
    )
    assert response.status_code == 429
