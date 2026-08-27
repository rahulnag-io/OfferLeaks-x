"""Tests for the M7 `company` field on `GET /analyses/{id}`: basic
verification status visible to everyone, advanced signals gated to Pro,
enforced server-side (never left to the frontend/client).
"""

import uuid
from datetime import UTC, datetime

from offerleaks.core.db import async_session_factory
from offerleaks.models.company import CompanyVerificationStatus, ProviderCheckOutcome
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.repositories.plan_repository import PlanRepository

REGISTER_BODY = {
    "email": "alice@example.com",
    "password": "correcthorsebattery",
    "full_name": "Alice",
}


async def _register_and_get_token(client) -> tuple[str, uuid.UUID]:
    response = await client.post("/auth/register", json=REGISTER_BODY)
    body = response.json()
    async with async_session_factory() as db:
        from sqlalchemy import select

        from offerleaks.models.user import User

        result = await db.execute(select(User).where(User.email == REGISTER_BODY["email"]))
        user = result.scalar_one()
    return body["access_token"], user.id


async def _create_analysis_with_company(
    user_id: uuid.UUID, *, advanced: bool = True
) -> uuid.UUID:
    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )

        company_repo = CompanyRepository(db)
        company = await company_repo.get_or_create_by_key(
            normalized_key="domain:gatedco.com", domain="gatedco.com", company_name="Gated Co"
        )
        if advanced:
            await company_repo.upsert_signal(
                company_id=company.id,
                verification_status=CompanyVerificationStatus.FOUND,
                domain_age_days=3650,
                domain_registered_at=datetime.now(UTC),
                domain_age_check=ProviderCheckOutcome.OK.value,
                website_reachable=True,
                website_reachability_check=ProviderCheckOutcome.OK.value,
                email_domain_match=True,
                evidence_ratio=1.0,
                last_checked_at=datetime.now(UTC),
            )
        analysis.company_id = company.id
        await db.flush()
        await db.commit()
        return analysis.id


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


async def test_free_user_sees_basic_verification_status_but_not_advanced(app, client):
    token, user_id = await _register_and_get_token(client)
    analysis_id = await _create_analysis_with_company(user_id)

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    company = response.json()["company"]
    assert company is not None
    assert company["verification_status"] == "found"
    assert company["domain"] == "gatedco.com"
    assert company["advanced"] is None


async def test_pro_user_sees_advanced_signals(app, client):
    token, user_id = await _register_and_get_token(client)
    await _subscribe_to_pro(user_id)
    analysis_id = await _create_analysis_with_company(user_id)

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    company = response.json()["company"]
    assert company["advanced"] is not None
    assert company["advanced"]["domain_age_days"] == 3650
    assert company["advanced"]["website_reachable"] is True
    assert company["advanced"]["email_domain_match"] is True


async def test_client_cannot_bypass_gating_via_query_params(app, client):
    """The gate is entirely server-side -- there is no request parameter
    that unlocks it."""
    token, user_id = await _register_and_get_token(client)
    analysis_id = await _create_analysis_with_company(user_id)

    response = await client.get(
        f"/analyses/{analysis_id}?pro=true&plan=pro&advanced=true",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["company"]["advanced"] is None


async def test_analysis_with_no_resolved_company_has_null_company_field(app, client):
    token, user_id = await _register_and_get_token(client)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        await db.commit()
        analysis_id = analysis.id

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["company"] is None


async def test_insufficient_evidence_is_reported_honestly_not_as_not_found(app, client):
    token, user_id = await _register_and_get_token(client)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        company_repo = CompanyRepository(db)
        company = await company_repo.get_or_create_by_key(
            normalized_key="name:ambiguous-co", domain=None, company_name="Ambiguous Co"
        )
        await company_repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
            domain_age_days=None,
            domain_registered_at=None,
            domain_age_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            website_reachable=None,
            website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            email_domain_match=None,
            evidence_ratio=0.0,
            last_checked_at=datetime.now(UTC),
        )
        analysis.company_id = company.id
        await db.flush()
        await db.commit()
        analysis_id = analysis.id

    response = await client.get(
        f"/analyses/{analysis_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    company_body = response.json()["company"]
    assert company_body["verification_status"] == "insufficient_evidence"
    assert company_body["verification_status"] != "not_found"
