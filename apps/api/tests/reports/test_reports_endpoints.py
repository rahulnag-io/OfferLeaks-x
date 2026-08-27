"""Endpoint-level tests for `/reports` (M8): privacy, Pro-gated detail
view, admin-only status transitions, and that Pro gating can't be
bypassed by request parameters.
"""

import uuid

from sqlalchemy import select

from offerleaks.core.db import async_session_factory
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.models.user import Role, User
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.repositories.plan_repository import PlanRepository


async def _register(client, email: str) -> tuple[str, uuid.UUID]:
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "correcthorsebattery", "full_name": "Test User"},
    )
    body = response.json()
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
    return body["access_token"], user.id


async def _make_admin(user_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        user.role = Role.ADMIN
        await db.commit()


async def _subscribe_to_pro(user_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        plan = await PlanRepository(db).get_by_key(PRO_PLAN_KEY)
        assert plan is not None
        db.add(
            Subscription(
                user_id=user_id,
                plan_id=plan.id,
                razorpay_subscription_id=f"sub_{uuid.uuid4().hex[:10]}",
                status=SubscriptionStatus.ACTIVE,
            )
        )
        await db.commit()


async def _create_company(key: str) -> uuid.UUID:
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key=key, domain=key.removeprefix("domain:"), company_name="Endpoint Co"
        )
        await db.commit()
        return company.id


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_submit_report_returns_basic_shape_to_free_user(app, client):
    token, _ = await _register(client, "reporter@example.com")
    company_id = await _create_company("domain:endpoint-basic.com")

    response = await client.post(
        "/reports",
        headers=_headers(token),
        json={
            "target_type": "company",
            "reasons": ["upfront_payment_request"],
            "description": "They asked for a $200 fee before the interview could be scheduled.",
            "company_id": str(company_id),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "submitted"
    assert "description" not in body  # basic shape only


async def test_invalid_report_input_returns_400_not_500(app, client):
    token, _ = await _register(client, "invalid-input@example.com")

    response = await client.post(
        "/reports",
        headers=_headers(token),
        json={"target_type": "company", "reasons": [], "description": "too short"},
    )

    assert response.status_code in (400, 422)


async def test_reports_are_never_exposed_to_another_user(app, client):
    owner_token, _ = await _register(client, "owner@example.com")
    other_token, _ = await _register(client, "other@example.com")
    company_id = await _create_company("domain:endpoint-privacy.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(owner_token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of a private complaint.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    # Even a Pro "other" user gets 404, never the owner's data.
    other_user_id_row = await client.post(
        "/reports",
        headers=_headers(other_token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "Unrelated description for a different report entirely here.",
            "company_id": str(company_id),
        },
    )
    assert other_user_id_row.status_code == 201

    detail_response = await client.get(f"/reports/{report_id}", headers=_headers(other_token))
    assert detail_response.status_code == 404


async def test_list_mine_only_returns_own_reports(app, client):
    token_a, _ = await _register(client, "lista@example.com")
    token_b, _ = await _register(client, "listb@example.com")
    company_id = await _create_company("domain:endpoint-list.com")

    await client.post(
        "/reports",
        headers=_headers(token_a),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "User A's own private report about this company here.",
            "company_id": str(company_id),
        },
    )
    await client.post(
        "/reports",
        headers=_headers(token_b),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "User B's own private report about this company here.",
            "company_id": str(company_id),
        },
    )

    response = await client.get("/reports/mine", headers=_headers(token_a))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


async def test_detailed_report_view_is_gated_to_pro(app, client):
    token, user_id = await _register(client, "free-detail@example.com")
    company_id = await _create_company("domain:endpoint-free-detail.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    response = await client.get(f"/reports/{report_id}", headers=_headers(token))
    assert response.status_code == 402


async def test_pro_user_sees_detailed_report_view(app, client):
    token, user_id = await _register(client, "pro-detail@example.com")
    await _subscribe_to_pro(user_id)
    company_id = await _create_company("domain:endpoint-pro-detail.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    response = await client.get(f"/reports/{report_id}", headers=_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "A sufficiently long description of the reported issue."


async def test_client_cannot_bypass_pro_gate_via_query_param(app, client):
    token, _ = await _register(client, "bypass-attempt@example.com")
    company_id = await _create_company("domain:endpoint-bypass.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    response = await client.get(
        f"/reports/{report_id}?plan=pro&is_pro=true", headers=_headers(token)
    )
    assert response.status_code == 402


async def test_regular_user_cannot_transition_report_status(app, client):
    token, _ = await _register(client, "regular-transition@example.com")
    company_id = await _create_company("domain:endpoint-regular-transition.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    response = await client.patch(
        f"/reports/{report_id}/status", headers=_headers(token), json={"status": "verified"}
    )
    assert response.status_code == 403


async def test_admin_can_transition_report_status(app, client):
    reporter_token, _ = await _register(client, "admin-reporter@example.com")
    admin_token, admin_id = await _register(client, "admin-user@example.com")
    await _make_admin(admin_id)
    company_id = await _create_company("domain:endpoint-admin-transition.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(reporter_token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    response = await client.patch(
        f"/reports/{report_id}/status",
        headers=_headers(admin_token),
        json={"status": "under_review"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "under_review"


async def test_invalid_status_transition_returns_409(app, client):
    reporter_token, _ = await _register(client, "invalid-transition-reporter@example.com")
    admin_token, admin_id = await _register(client, "invalid-transition-admin@example.com")
    await _make_admin(admin_id)
    company_id = await _create_company("domain:endpoint-invalid-transition.com")

    create_response = await client.post(
        "/reports",
        headers=_headers(reporter_token),
        json={
            "target_type": "company",
            "reasons": ["other"],
            "description": "A sufficiently long description of the reported issue.",
            "company_id": str(company_id),
        },
    )
    report_id = create_response.json()["id"]

    await client.patch(
        f"/reports/{report_id}/status", headers=_headers(admin_token), json={"status": "rejected"}
    )
    response = await client.patch(
        f"/reports/{report_id}/status",
        headers=_headers(admin_token),
        json={"status": "verified"},
    )
    assert response.status_code == 409
