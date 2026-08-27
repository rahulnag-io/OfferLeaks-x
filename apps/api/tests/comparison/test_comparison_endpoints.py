"""Endpoint-level tests for `GET /comparison` (M8): Pro gating enforced
server-side, ownership enforced, same-offer rejection.
"""

import uuid

from sqlalchemy import select

from offerleaks.core.db import async_session_factory
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
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


async def _create_analysis(user_id: uuid.UUID, *, risk_score: int, file_name: str) -> uuid.UUID:
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/{file_name}",
            file_name=file_name,
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        await repo.create_verdict(
            analysis_id=analysis.id,
            risk_score=risk_score,
            red_flags=[],
            reasoning="test",
            confidence=0.8,
        )
        await db.commit()
        return analysis.id


async def test_comparison_is_gated_to_pro(app, client):
    token, user_id = await _register(client, "free-compare@example.com")
    a = await _create_analysis(user_id, risk_score=80, file_name="a.pdf")
    b = await _create_analysis(user_id, risk_score=20, file_name="b.pdf")

    response = await client.get(
        f"/comparison?analysis_id_a={a}&analysis_id_b={b}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 402


async def test_pro_user_can_compare_own_offers(app, client):
    token, user_id = await _register(client, "pro-compare@example.com")
    await _subscribe_to_pro(user_id)
    a = await _create_analysis(user_id, risk_score=80, file_name="a.pdf")
    b = await _create_analysis(user_id, risk_score=20, file_name="b.pdf")

    response = await client.get(
        f"/comparison?analysis_id_a={a}&analysis_id_b={b}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["left"]["risk_score"] == 80
    assert body["right"]["risk_score"] == 20


async def test_comparison_rejects_another_users_offer_via_api(app, client):
    token, user_id = await _register(client, "pro-attacker@example.com")
    await _subscribe_to_pro(user_id)
    _, other_id = await _register(client, "pro-victim@example.com")

    own = await _create_analysis(user_id, risk_score=80, file_name="own.pdf")
    other = await _create_analysis(other_id, risk_score=20, file_name="other.pdf")

    response = await client.get(
        f"/comparison?analysis_id_a={own}&analysis_id_b={other}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_comparing_offer_with_itself_via_api_returns_400(app, client):
    token, user_id = await _register(client, "pro-same-offer@example.com")
    await _subscribe_to_pro(user_id)
    a = await _create_analysis(user_id, risk_score=80, file_name="a.pdf")

    response = await client.get(
        f"/comparison?analysis_id_a={a}&analysis_id_b={a}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
