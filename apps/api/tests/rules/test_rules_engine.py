"""Tests for `offerleaks.services.rules_engine.RulesEngine` (M6).

`match` is exercised against real `ScamPattern` rows in Postgres (not
mocked) -- the point of this test module is verifying the actual
keyword-matching SQL/Python logic against known scam-letter text, the
same "runs against real Postgres" convention as the rest of the suite.
`evidence_coverage`/`recommended_actions_for` are pure functions, tested
directly with hand-built `RedFlag` lists.
"""

import uuid

from offerleaks.core.db import async_session_factory
from offerleaks.models.scam_pattern import ScamPattern, ScamPatternSeverity
from offerleaks.schemas.ai import RedFlag, RedFlagSeverity
from offerleaks.services.rules_engine import RulesEngine

LEGITIMATE_LETTER = (
    "Dear Alice, we are pleased to offer you the position of Senior Engineer "
    "at Acme Corp, starting Monday. Your manager will be Priya Shah. "
    "Please find the full offer details attached."
)

SCAM_LETTER = (
    "Congratulations! To secure this role, please pay a processing fee of "
    "$200. Offer expires today, so act immediately by replying to this "
    "email from our recruiter at recruiter@gmail.com. No interview "
    "required -- you have been hired without interview based on your "
    "resume."
)


async def _add_pattern(
    *, key: str, keywords: list[str], severity: ScamPatternSeverity = ScamPatternSeverity.HIGH
) -> None:
    async with async_session_factory() as db:
        db.add(
            ScamPattern(
                id=uuid.uuid4(),
                key=key,
                title=f"Test pattern: {key}",
                description="A pattern created for a test.",
                severity=severity,
                keywords=keywords,
                is_active=True,
            )
        )
        await db.commit()


async def test_match_returns_nothing_for_a_clean_letter():
    async with async_session_factory() as db:
        result = await RulesEngine(db).match(text=LEGITIMATE_LETTER)

    # Only asserts against the seeded migration patterns (present in every
    # test run, not truncated by `_clean_state`) -- the clean letter
    # shouldn't trip any of them.
    assert result.matched_patterns == []
    assert result.pattern_red_flags == []


async def test_match_finds_seeded_patterns_in_a_scam_letter():
    async with async_session_factory() as db:
        result = await RulesEngine(db).match(text=SCAM_LETTER)

    matched_keys = {m.pattern_key for m in result.matched_patterns}
    # From the seeded starter library (migration a1c6f9d2b3e4): the scam
    # letter above deliberately trips the fee, urgency, free-email-domain,
    # and no-interview patterns.
    assert "upfront_processing_fee" in matched_keys
    assert "urgency_pressure_tactic" in matched_keys
    assert "free_email_domain_official" in matched_keys
    assert "no_interview_process" in matched_keys
    assert len(result.pattern_red_flags) == len(result.matched_patterns)


async def test_match_ignores_inactive_patterns():
    await _add_pattern(key="test_inactive_marker_pattern", keywords=["zzz_unique_marker_zzz"])
    async with async_session_factory() as db:
        db.add(
            ScamPattern(
                id=uuid.uuid4(),
                key="test_truly_inactive",
                title="Inactive",
                description="Should never match.",
                severity=ScamPatternSeverity.HIGH,
                keywords=["zzz_unique_marker_zzz"],
                is_active=False,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        result = await RulesEngine(db).match(text="this contains zzz_unique_marker_zzz twice")

    matched_keys = {m.pattern_key for m in result.matched_patterns}
    assert "test_inactive_marker_pattern" in matched_keys
    assert "test_truly_inactive" not in matched_keys


async def test_match_is_case_insensitive():
    await _add_pattern(key="test_case_pattern", keywords=["Wire Transfer Details"])

    async with async_session_factory() as db:
        result = await RulesEngine(db).match(text="please send your WIRE TRANSFER DETAILS now")

    assert any(m.pattern_key == "test_case_pattern" for m in result.matched_patterns)


async def test_match_evidence_quote_contains_the_matched_keyword():
    await _add_pattern(key="test_evidence_pattern", keywords=["totally unique phrase xyz"])

    async with async_session_factory() as db:
        result = await RulesEngine(db).match(
            text="Before. totally unique phrase xyz. After the match."
        )

    flag = next(
        f for f in result.pattern_red_flags if f.title == "Test pattern: test_evidence_pattern"
    )
    assert flag.evidence_quote is not None
    assert "totally unique phrase xyz" in flag.evidence_quote


def test_evidence_coverage_of_empty_list_is_zero():
    assert RulesEngine.evidence_coverage([]) == 0.0


def test_evidence_coverage_counts_flags_with_a_quote():
    flags = [
        RedFlag(title="a", description="a", severity=RedFlagSeverity.LOW, evidence_quote="quote"),
        RedFlag(title="b", description="b", severity=RedFlagSeverity.LOW, evidence_quote=None),
        RedFlag(title="c", description="c", severity=RedFlagSeverity.LOW, evidence_quote="quote"),
        RedFlag(title="d", description="d", severity=RedFlagSeverity.LOW, evidence_quote=None),
    ]
    assert RulesEngine.evidence_coverage(flags) == 0.5


def test_recommended_actions_for_high_risk_includes_high_risk_actions():
    flags = [
        RedFlag(title="a", description="a", severity=RedFlagSeverity.HIGH, evidence_quote=None)
    ]
    actions = RulesEngine.recommended_actions_for(risk_score=85, red_flags=flags)

    assert 2 <= len(actions) <= 4
    assert any("do not send money" in a.lower() for a in actions)


def test_recommended_actions_for_low_risk_no_flags_stays_reassuring():
    actions = RulesEngine.recommended_actions_for(risk_score=5, red_flags=[])

    assert 2 <= len(actions) <= 4
    assert not any("do not send money" in a.lower() for a in actions)


def test_recommended_actions_high_severity_flag_escalates_even_with_low_score():
    """A single HIGH-severity flag should escalate the recommendation even
    if the model's overall risk_score happened to stay low -- the rules
    engine's action selection must not defer entirely to the AI's score.
    """
    flags = [
        RedFlag(title="a", description="a", severity=RedFlagSeverity.HIGH, evidence_quote=None)
    ]
    actions = RulesEngine.recommended_actions_for(risk_score=10, red_flags=flags)

    assert any("do not send money" in a.lower() for a in actions)


def test_recommended_actions_capped_at_four():
    flags = [
        RedFlag(title="a", description="a", severity=RedFlagSeverity.HIGH, evidence_quote=None)
    ]
    actions = RulesEngine.recommended_actions_for(risk_score=100, red_flags=flags)
    assert len(actions) <= 4
