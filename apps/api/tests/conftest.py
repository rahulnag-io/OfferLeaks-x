"""Shared pytest fixtures."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from offerleaks.core.db import engine
from offerleaks.core.redis import redis_client
from offerleaks.main import create_app


@pytest.fixture(autouse=True)
async def _clean_state():
    """Reset per-test state before every test: the `users` table (and
    everything that cascades from it -- analyses, credit balances,
    subscriptions, usage ledger entries) and Redis.

    `plans` and `scam_patterns` (M6) are deliberately *not* truncated
    here -- both are seed/reference data (seeded by migration, not
    per-test state, matching how `ScamPatternRepository`/`PlanRepository`
    are read-only in v1; see those modules' docstrings), and truncating
    them would just make every M6 test re-seed rows the migrations
    already provide. Tests that *do* need to mutate a reference row
    (e.g. setting `Plan.razorpay_plan_id` to make Pro subscribable, or
    inserting an ad hoc `ScamPattern` to test a specific keyword) must
    restore it themselves -- the two statements below undo exactly those
    two known mutation points so a test that forgets doesn't leak state
    into every test that runs after it.
    """
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE users CASCADE"))
        # Undo `tests/billing/*`'s `_set_pro_plan_razorpay_id` helper --
        # otherwise a test asserting "Pro isn't subscribable yet" fails
        # depending on what ran before it in the same session.
        await conn.execute(
            text("UPDATE plans SET razorpay_plan_id = NULL WHERE key = 'pro'")
        )
        # Undo `tests/rules/test_rules_engine.py`'s ad hoc pattern
        # inserts -- all of them use a `test_`-prefixed key by
        # convention specifically so this cleanup can target them
        # without touching the seeded starter library.
        await conn.execute(text("DELETE FROM scam_patterns WHERE key LIKE 'test_%'"))
        # M7: `companies`/`company_signals` are per-run cached *data*
        # (shared across users, keyed by normalized domain/company
        # identity), not seed/reference data like `plans`/`scam_patterns`
        # above -- so, unlike those two, they get a real per-test reset.
        # `company_signals` cascades from `companies` (`ON DELETE
        # CASCADE`), so truncating `companies` alone is enough.
        await conn.execute(text("TRUNCATE TABLE companies CASCADE"))
        # M8: `reports` cascades from `users` (`ON DELETE CASCADE`), so
        # the `TRUNCATE TABLE users CASCADE` above already clears it --
        # no separate statement needed (TRUNCATE ... CASCADE truncates
        # every table with an FK reference to the named table(s), not
        # just tables whose FK itself specifies ON DELETE CASCADE).
    await redis_client.flushdb()
    yield


@pytest.fixture
def app():
    """The FastAPI app instance, exposed separately from `client` so tests
    can use `app.dependency_overrides` (e.g. swapping in fake providers
    for the analysis endpoints) without constructing their own app.
    """
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
