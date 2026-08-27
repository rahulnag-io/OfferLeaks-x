"""Tests for `ReportService` against real Postgres (M8). Covers
submission/validation, ownership, duplicate-window detection, status
transitions, and internal reputation-signal integrity.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from offerleaks.core.db import async_session_factory
from offerleaks.models.company import CompanyVerificationStatus, ProviderCheckOutcome
from offerleaks.models.report import Report, ReportReason, ReportStatus, ReportTargetType
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.report_service import (
    InvalidStatusTransitionError,
    ReportNotFoundError,
    ReportService,
    ReportSubmission,
    ReportValidationError,
)

_VALID_DESCRIPTION = "They asked me to pay a $200 registration fee before any interview."


async def _create_user(email: str | None = None) -> User:
    async with async_session_factory() as db:
        user = User(
            email=email or f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash"
        )
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
        return user


async def _create_company(key: str, *, domain: str | None = None) -> uuid.UUID:
    """Mirrors real usage: every `Company` that can ever be reported on
    already went through `CompanyProfileService.resolve_for_analysis`
    (there is no other creation path -- see `models/company.py`), which
    always creates a placeholder `CompanySignal` row alongside it. Test
    companies replicate that guarantee here rather than the report
    domain silently tolerating a company with no signal row, which
    cannot happen for a real, reportable company.
    """
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key=key, domain=domain, company_name="Test Co"
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
            domain_age_days=None,
            domain_registered_at=None,
            domain_age_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            website_reachable=None,
            website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            email_domain_match=None,
            evidence_ratio=0.0,
            last_checked_at=datetime(1970, 1, 1, tzinfo=UTC),
        )
        await db.commit()
        return company.id


async def _create_analysis(user_id: uuid.UUID, *, company_id: uuid.UUID | None = None) -> uuid.UUID:
    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        if company_id is not None:
            analysis.company_id = company_id
            await db.flush()
        await db.commit()
        return analysis.id


def _submission(**overrides) -> ReportSubmission:
    defaults = dict(
        target_type=ReportTargetType.COMPANY,
        reasons=[ReportReason.UPFRONT_PAYMENT_REQUEST],
        description=_VALID_DESCRIPTION,
    )
    defaults.update(overrides)
    return ReportSubmission(**defaults)


# --- Submission / validation ---


async def test_submit_company_report_succeeds():
    user = await _create_user()
    company_id = await _create_company("domain:acme-report.com", domain="acme-report.com")
    async with async_session_factory() as db:
        service = ReportService(db)
        report = await service.submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        assert report.status == ReportStatus.SUBMITTED
        assert report.company_id == company_id
        assert report.is_duplicate is False


async def test_company_report_requires_company_id():
    user = await _create_user()
    async with async_session_factory() as db:
        service = ReportService(db)
        with pytest.raises(ReportValidationError):
            await service.submit_report(user=user, submission=_submission(company_id=None))


async def test_description_too_short_is_rejected():
    user = await _create_user()
    company_id = await _create_company("domain:short-desc.com", domain="short-desc.com")
    async with async_session_factory() as db:
        service = ReportService(db)
        with pytest.raises(ReportValidationError):
            await service.submit_report(
                user=user,
                submission=_submission(company_id=company_id, description="too short"),
            )


async def test_at_least_one_reason_is_required():
    user = await _create_user()
    company_id = await _create_company("domain:no-reason.com", domain="no-reason.com")
    async with async_session_factory() as db:
        service = ReportService(db)
        with pytest.raises(ReportValidationError):
            await service.submit_report(
                user=user, submission=_submission(company_id=company_id, reasons=[])
            )


async def test_recruiter_report_requires_target_detail():
    user = await _create_user()
    async with async_session_factory() as db:
        service = ReportService(db)
        with pytest.raises(ReportValidationError):
            await service.submit_report(
                user=user,
                submission=_submission(
                    target_type=ReportTargetType.RECRUITER, target_detail=None
                ),
            )


async def test_website_report_with_target_detail_succeeds():
    user = await _create_user()
    async with async_session_factory() as db:
        service = ReportService(db)
        report = await service.submit_report(
            user=user,
            submission=_submission(
                target_type=ReportTargetType.WEBSITE, target_detail="https://scam-example.test"
            ),
        )
        assert report.target_detail == "https://scam-example.test"
        assert report.company_id is None


# --- Offer reports reuse existing ownership/company context ---


async def test_offer_report_derives_company_from_the_analysis():
    user = await _create_user()
    company_id = await _create_company("domain:offer-report.com", domain="offer-report.com")
    analysis_id = await _create_analysis(user.id, company_id=company_id)

    async with async_session_factory() as db:
        service = ReportService(db)
        report = await service.submit_report(
            user=user,
            submission=_submission(
                target_type=ReportTargetType.OFFER,
                analysis_id=analysis_id,
                # A client-supplied company_id must never override the
                # offer's own resolved company (M8 §11).
                company_id=uuid.uuid4(),
            ),
        )
        assert report.analysis_id == analysis_id
        assert report.company_id == company_id


async def test_offer_report_rejects_an_analysis_owned_by_another_user():
    owner = await _create_user()
    other_user = await _create_user()
    analysis_id = await _create_analysis(owner.id)

    async with async_session_factory() as db:
        service = ReportService(db)
        with pytest.raises(ReportValidationError):
            await service.submit_report(
                user=other_user,
                submission=_submission(
                    target_type=ReportTargetType.OFFER, analysis_id=analysis_id
                ),
            )


# --- Duplicate-detection accuracy ---


async def test_second_similar_report_for_same_company_is_flagged_duplicate():
    user = await _create_user()
    company_id = await _create_company("domain:dupe-co.com", domain="dupe-co.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        first = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="They asked me to wire $300 before starting the job.",
            ),
        )
        second = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="This company asked me to wire $300 before I could start the job.",
            ),
        )

    assert second.is_duplicate is True
    assert second.duplicate_of_report_id == first.id


async def test_distinct_description_for_same_company_is_not_a_duplicate():
    user = await _create_user()
    company_id = await _create_company("domain:distinct-co.com", domain="distinct-co.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="They asked me to wire $300 before starting the job.",
            ),
        )
        second = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description=(
                    "The offer letter impersonated a real company using a lookalike domain."
                ),
            ),
        )

    assert second.is_duplicate is False


async def test_similar_description_for_a_different_company_is_not_a_duplicate():
    user = await _create_user()
    company_a = await _create_company("domain:companya.com", domain="companya.com")
    company_b = await _create_company("domain:companyb.com", domain="companyb.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_a,
                description="They asked me to wire $300 before starting the job.",
            ),
        )
        second = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_b,
                description="They asked me to wire $300 before starting the job.",
            ),
        )

    assert second.is_duplicate is False


async def test_similar_report_outside_the_duplicate_window_is_not_flagged():
    user = await _create_user()
    company_id = await _create_company("domain:stale-window.com", domain="stale-window.com")

    async with async_session_factory() as db:
        old_report = Report(
            user_id=user.id,
            target_type=ReportTargetType.COMPANY,
            company_id=company_id,
            reasons=[ReportReason.UPFRONT_PAYMENT_REQUEST.value],
            description="They asked me to wire $300 before starting the job.",
            description_normalized="they asked me to wire 300 before starting the job",
            status=ReportStatus.SUBMITTED,
            is_duplicate=False,
        )
        db.add(old_report)
        await db.flush()
        # Backdate it past the configured duplicate window.
        old_report.created_at = datetime.now(UTC) - timedelta(days=90)
        await db.flush()
        await db.commit()

    async with async_session_factory() as db:
        service = ReportService(db)
        new_report = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="They asked me to wire $300 before starting the job.",
            ),
        )

    assert new_report.is_duplicate is False


async def test_legitimate_repeat_report_from_different_users_is_still_a_duplicate_for_reputation():
    """M8 §7: duplicate detection is about the *complaint*, not the
    *reporter* -- two different users independently reporting the same
    live scam within the window should still count as one signal, not
    two, so reputation isn't inflated by volume alone."""
    user_a = await _create_user()
    user_b = await _create_user()
    company_id = await _create_company("domain:multi-reporter.com", domain="multi-reporter.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        await service.submit_report(
            user=user_a,
            submission=_submission(
                company_id=company_id,
                description="They asked me to wire $300 before starting the job.",
            ),
        )
        second = await service.submit_report(
            user=user_b,
            submission=_submission(
                company_id=company_id,
                description="This employer asked me to wire $300 before I could start the job.",
            ),
        )

    assert second.is_duplicate is True


# --- Status transitions ---


async def test_new_report_starts_submitted():
    user = await _create_user()
    company_id = await _create_company("domain:initial-status.com", domain="initial-status.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        assert report.status == ReportStatus.SUBMITTED


async def test_valid_transition_submitted_to_under_review_succeeds():
    user = await _create_user()
    company_id = await _create_company("domain:valid-transition.com", domain="valid-transition.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        updated = await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.UNDER_REVIEW
        )
        assert updated.status == ReportStatus.UNDER_REVIEW


async def test_transition_from_rejected_terminal_state_is_rejected():
    user = await _create_user()
    company_id = await _create_company("domain:terminal-state.com", domain="terminal-state.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.REJECTED
        )

    async with async_session_factory() as db:
        with pytest.raises(InvalidStatusTransitionError):
            await ReportService(db).transition_status(
                report_id=report_id, to_status=ReportStatus.UNDER_REVIEW
            )


async def test_transition_from_verified_terminal_state_is_rejected():
    user = await _create_user()
    company_id = await _create_company(
        "domain:verified-terminal.com", domain="verified-terminal.com"
    )
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.VERIFIED
        )

    async with async_session_factory() as db:
        with pytest.raises(InvalidStatusTransitionError):
            await ReportService(db).transition_status(
                report_id=report_id, to_status=ReportStatus.REJECTED
            )


async def test_transition_of_nonexistent_report_raises_not_found():
    async with async_session_factory() as db:
        with pytest.raises(ReportNotFoundError):
            await ReportService(db).transition_status(
                report_id=uuid.uuid4(), to_status=ReportStatus.UNDER_REVIEW
            )


async def test_repeated_identical_transition_is_a_safe_no_op():
    """Retrying the same status-change request (client retry, duplicate
    delivery) must not raise and must not change state further (M8 §13:
    "safe under retries")."""
    user = await _create_user()
    company_id = await _create_company("domain:retry-safe.com", domain="retry-safe.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        first = await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.VERIFIED
        )
    async with async_session_factory() as db:
        second = await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.VERIFIED
        )

    assert first.status == ReportStatus.VERIFIED
    assert second.status == ReportStatus.VERIFIED


# --- Internal reputation-score integrity ---


async def test_verified_report_increments_internal_reputation_signal():
    user = await _create_user()
    company_id = await _create_company("domain:reputation-up.com", domain="reputation-up.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.VERIFIED
        )

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company_id)
        assert signal is not None
        assert signal.verified_report_count == 1
        assert signal.internal_reputation_score is not None
        assert signal.internal_reputation_score > 0


async def test_rejected_report_never_contributes_to_reputation():
    user = await _create_user()
    company_id = await _create_company(
        "domain:reputation-rejected.com", domain="reputation-rejected.com"
    )
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.REJECTED
        )

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company_id)
        assert signal is not None
        assert signal.verified_report_count == 0
        assert signal.internal_reputation_score is None


async def test_only_submitted_or_under_review_reports_can_become_eligible():
    """Guards against a report contributing via any path other than the
    one documented eligible transition into VERIFIED."""
    user = await _create_user()
    company_id = await _create_company("domain:eligible-path.com", domain="eligible-path.com")
    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=user, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.UNDER_REVIEW
        )
    async with async_session_factory() as db:
        updated = await ReportService(db).transition_status(
            report_id=report_id, to_status=ReportStatus.VERIFIED
        )
        assert updated.status == ReportStatus.VERIFIED


async def test_duplicate_reports_do_not_double_count_even_if_both_are_verified():
    """M8 §13: "prevent duplicate reports from unnecessarily multiplying
    internal reputation influence" -- even in the edge case where a
    flagged-duplicate report is independently moved to VERIFIED (e.g. a
    reviewer working through a queue and not carefully deduplicating by
    hand), the authoritative count (`WHERE is_duplicate = false`) still
    excludes it.
    """
    user = await _create_user()
    company_id = await _create_company("domain:dupe-verified.com", domain="dupe-verified.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        first = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="They asked me to wire $300 before starting the job.",
            ),
        )
        second = await service.submit_report(
            user=user,
            submission=_submission(
                company_id=company_id,
                description="This company asked me to wire $300 before I could start the job.",
            ),
        )
    assert second.is_duplicate is True

    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=first.id, to_status=ReportStatus.VERIFIED
        )
    async with async_session_factory() as db:
        await ReportService(db).transition_status(
            report_id=second.id, to_status=ReportStatus.VERIFIED
        )

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company_id)
        assert signal is not None
        # Only the original (non-duplicate) verified report counts.
        assert signal.verified_report_count == 1


async def test_recompute_after_multiple_verified_reports_is_a_fresh_count_not_an_increment():
    user = await _create_user()
    company_id = await _create_company("domain:multi-verified.com", domain="multi-verified.com")
    report_ids = []
    descriptions = [
        "They asked me to wire $300 before starting the job.",
        "The offer letter used a free email address and no company domain.",
        "They pressured me to respond within one hour or lose the offer.",
    ]
    async with async_session_factory() as db:
        service = ReportService(db)
        for description in descriptions:
            report = await service.submit_report(
                user=user,
                submission=_submission(company_id=company_id, description=description),
            )
            report_ids.append(report.id)

    async with async_session_factory() as db:
        service = ReportService(db)
        for report_id in report_ids:
            await service.transition_status(report_id=report_id, to_status=ReportStatus.VERIFIED)

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company_id)
        assert signal is not None
        assert signal.verified_report_count == 3


# --- Ownership / privacy ---


async def test_get_owned_report_rejects_another_users_report():
    owner = await _create_user()
    other_user = await _create_user()
    company_id = await _create_company("domain:privacy-check.com", domain="privacy-check.com")

    async with async_session_factory() as db:
        report = await ReportService(db).submit_report(
            user=owner, submission=_submission(company_id=company_id)
        )
        report_id = report.id

    async with async_session_factory() as db:
        with pytest.raises(ReportNotFoundError):
            await ReportService(db).get_owned_report(user=other_user, report_id=report_id)


async def test_list_my_reports_only_returns_own_reports():
    user_a = await _create_user()
    user_b = await _create_user()
    company_id = await _create_company("domain:list-scope.com", domain="list-scope.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        await service.submit_report(user=user_a, submission=_submission(company_id=company_id))
        await service.submit_report(user=user_b, submission=_submission(company_id=company_id))

    async with async_session_factory() as db:
        reports, total = await ReportService(db).list_my_reports(user=user_a, limit=20, offset=0)
        assert total == 1
        assert all(r.user_id == user_a.id for r in reports)
