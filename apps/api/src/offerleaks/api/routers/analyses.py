"""Upload & analysis-status endpoints (Version 3: Upload -> OCR -> AI
Verdict).

Routers stay thin: request/response translation and status-code mapping
only, all business logic lives in `AnalysisService` (architecture.md §0.3).
The actual OCR/AI work never runs inline here -- `POST /analyses` returns
202 with a `PENDING` analysis the moment the file is validated, scanned,
and stored; `GET /analyses/{id}` is what the frontend polls.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.core.db import get_db_session
from offerleaks.core.rate_limit import rate_limit
from offerleaks.core.redis import get_redis
from offerleaks.models.analysis import Analysis, AnalysisStatus, Verdict
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.user import User
from offerleaks.providers.factory import (
    get_domain_age_provider,
    get_malware_scan_provider,
    get_storage_provider,
    get_website_reachability_provider,
)
from offerleaks.providers.malware_scan import MalwareScanProvider
from offerleaks.providers.storage import StorageProvider
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.repositories.credit_repository import CreditRepository
from offerleaks.schemas.analysis import AnalysisListResponse, AnalysisResponse, VerdictResponse
from offerleaks.schemas.company import CompanyAdvancedSignals, CompanyProfileResponse
from offerleaks.services.analysis_service import (
    AnalysisNotFoundError,
    AnalysisNotReadyForRecheckError,
    AnalysisService,
    FileValidationError,
    InsufficientCreditsError,
    MalwareDetectedError,
    MonthlyAnalysisLimitExceededError,
    QueueUnavailableError,
    ScanUnavailableForUploadError,
)
from offerleaks.services.company_profile_service import CompanyProfileService
from offerleaks.services.entitlement_service import EntitlementService
from offerleaks.services.file_validation import FileTooLargeError

router = APIRouter(prefix="/analyses", tags=["analyses"])

# Upload is the most expensive, most abuse-prone route in the system
# (§0.11) -- rate-limited harder than auth, and per-user *and* per-IP
# since (unlike login) there's always an authenticated caller here.
_upload_rate_limit = rate_limit(
    key="upload", max_attempts=5, window_seconds=300, per_user=True
)
# Re-check re-enters the same OCR/AI pipeline as upload (and can be free,
# see `AnalysisService.recheck_analysis`), so it gets the same rate limit
# rather than a lighter one -- a free re-check is still real provider cost.
_recheck_rate_limit = rate_limit(
    key="recheck", max_attempts=5, window_seconds=300, per_user=True
)

_MAX_LIST_LIMIT = 50
_DEFAULT_LIST_LIMIT = 20


def _get_analysis_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[StorageProvider, Depends(get_storage_provider)],
    malware_scanner: Annotated[MalwareScanProvider, Depends(get_malware_scan_provider)],
) -> AnalysisService:
    return AnalysisService(db, storage, malware_scanner)


async def _build_company_response(
    analysis: Analysis, db: AsyncSession, user: User
) -> CompanyProfileResponse | None:
    """M7: attaches the resolved company's current profile, if any, with
    advanced signals gated to Pro server-side (never left to the
    frontend to hide -- M7 §12/§21).

    Also opportunistically triggers a background refresh via
    `ensure_fresh` when the profile is missing/stale -- staleness must be
    caught on read, not only when some *new*, unrelated analysis happens
    to re-resolve the same company (which could be arbitrarily far in
    the future, or never). `ensure_fresh` itself never blocks: it only
    enqueues a job (subject to its own lock/rate-limit guards) and
    returns immediately, so this stays a fast, synchronous read -- the
    response below always reflects whatever is currently known, however
    fresh, exactly as before.
    """
    if analysis.company_id is None:
        return None

    company = await CompanyRepository(db).get_by_id(analysis.company_id)
    if company is None:
        return None

    service = CompanyProfileService(
        db,
        await get_redis(),
        get_domain_age_provider(),
        get_website_reachability_provider(),
    )
    await service.ensure_fresh(company)
    profile = await service.get_profile(company)
    if profile is None:
        return None

    plan_resolution = await EntitlementService(db).resolve_plan(user.id)
    is_pro = plan_resolution.plan.key == PRO_PLAN_KEY

    return CompanyProfileResponse(
        company_name=profile.company_name,
        domain=profile.domain,
        verification_status=profile.verification_status,
        last_checked_at=profile.last_checked_at,
        advanced=(
            CompanyAdvancedSignals(
                domain_age_days=profile.domain_age_days,
                website_reachable=profile.website_reachable,
                email_domain_match=profile.email_domain_match,
            )
            if is_pro
            else None
        ),
    )


async def _to_analysis_response(
    analysis: Analysis,
    db: AsyncSession,
    user: User,
    *,
    verdict: Verdict | None = None,
    credit_cost: int | None = None,
    credit_refunded: bool | None = None,
) -> AnalysisResponse:
    """Builds the response DTO. `verdict`/`credit_cost`/`credit_refunded`
    can be passed in by callers that already fetched them in bulk (the
    list endpoint); left `None` here means "look this one up
    individually" (the create/get/recheck endpoints, which only ever
    handle one analysis at a time)."""
    if verdict is None:
        verdict = await AnalysisRepository(db).get_verdict(analysis.id)
    if credit_cost is None:
        amounts = await CreditRepository(db).get_consume_amounts_for([analysis.id])
        credit_cost = amounts.get(analysis.id, 0)
    if credit_refunded is None:
        refunded_ids = await CreditRepository(db).get_refunded_analysis_ids([analysis.id])
        credit_refunded = analysis.id in refunded_ids

    return AnalysisResponse(
        id=analysis.id,
        status=analysis.status,
        file_name=analysis.file_name,
        prompt_version=analysis.prompt_version,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        updated_at=analysis.updated_at,
        verdict=VerdictResponse.model_validate(verdict) if verdict is not None else None,
        source_analysis_id=analysis.source_analysis_id,
        credit_cost=credit_cost,
        credit_refunded=credit_refunded,
        company=await _build_company_response(analysis, db, user),
    )


@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analysis_service: Annotated[AnalysisService, Depends(_get_analysis_service)],
    _: Annotated[None, Depends(_upload_rate_limit)],
    file: UploadFile = File(...),
) -> AnalysisResponse:
    file_bytes = await file.read()

    try:
        analysis = await analysis_service.create_analysis(
            user=current_user,
            file_bytes=file_bytes,
            file_name=file.filename or "upload",
        )
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
        ) from exc
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except MalwareDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This file failed a malware/virus scan and was rejected.",
        ) from exc
    except ScanUnavailableForUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File scanning is temporarily unavailable. Please try again shortly.",
        ) from exc
    except MonthlyAnalysisLimitExceededError as exc:
        # 402, same status family as InsufficientCreditsError -- both are
        # "you can't do this on your current plan/balance," the client's
        # remediation (upgrade or buy credits) is the same shape either
        # way, just a different reason string.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"You've reached your plan's monthly analysis limit "
                f"({exc.limit}). Upgrade to Pro for unlimited analyses."
            ),
        ) from exc
    except InsufficientCreditsError as exc:
        # 402 Payment Required: the paywall. Enforced here (server-side,
        # from the authoritative CreditService) regardless of what the
        # frontend's last-known balance display shows.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Not enough credits to start this analysis "
                f"(requires {exc.required}, you have {exc.available})."
            ),
        ) from exc
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We couldn't start processing this document. Please try again shortly.",
        ) from exc

    return await _to_analysis_response(analysis, db, current_user)


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analysis_service: Annotated[AnalysisService, Depends(_get_analysis_service)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[AnalysisStatus | None, Query(alias="status")] = None,
) -> AnalysisListResponse:
    """Version 5 dashboard/history: the current user's own analyses,
    newest first, optionally filtered by status. Never accepts a
    user id -- identity is always `current_user` (architecture.md §0.10)."""
    items, total = await analysis_service.list_analyses(
        user=current_user, limit=limit, offset=offset, status_filter=status_filter
    )

    verdicts = await AnalysisRepository(db).get_verdicts_for([item.id for item in items])
    costs = await CreditRepository(db).get_consume_amounts_for([item.id for item in items])
    refunded_ids = await CreditRepository(db).get_refunded_analysis_ids([item.id for item in items])

    responses = [
        await _to_analysis_response(
            item,
            db,
            current_user,
            verdict=verdicts.get(item.id),
            credit_cost=costs.get(item.id, 0),
            credit_refunded=item.id in refunded_ids,
        )
        for item in items
    ]
    return AnalysisListResponse(items=responses, total=total, limit=limit, offset=offset)


@router.post(
    "/{analysis_id}/recheck",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def recheck_analysis(
    analysis_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analysis_service: Annotated[AnalysisService, Depends(_get_analysis_service)],
    _: Annotated[None, Depends(_recheck_rate_limit)],
) -> AnalysisResponse:
    """Version 5 "re-check": re-runs the pipeline for a past analysis
    against the same stored file. See `AnalysisService.recheck_analysis`
    for the free-vs-charged pricing rule."""
    try:
        parsed_id = uuid.UUID(analysis_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found"
        ) from exc

    try:
        analysis = await analysis_service.recheck_analysis(
            user=current_user, analysis_id=parsed_id
        )
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found"
        ) from exc
    except AnalysisNotReadyForRecheckError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis is still being processed and can't be re-checked yet.",
        ) from exc
    except InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Not enough credits to re-check this analysis "
                f"(requires {exc.required}, you have {exc.available})."
            ),
        ) from exc
    except QueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We couldn't start re-checking this document. Please try again shortly.",
        ) from exc

    return await _to_analysis_response(analysis, db, current_user)


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analysis_service: Annotated[AnalysisService, Depends(_get_analysis_service)],
) -> AnalysisResponse:
    try:
        parsed_id = uuid.UUID(analysis_id)
    except ValueError as exc:
        # Not a well-formed id -> same 404 as "not found, or not yours"
        # below. Distinguishing "malformed" from "doesn't exist" leaks
        # nothing useful and just adds another response shape to defend.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found"
        ) from exc

    try:
        analysis = await analysis_service.get_owned_analysis(
            user=current_user, analysis_id=parsed_id
        )
    except AnalysisNotFoundError as exc:
        # 404, not 403: an analysis owned by another user should be
        # indistinguishable from one that doesn't exist at all (same
        # no-enumeration principle §0.11 applies to auth error shapes).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found"
        ) from exc

    return await _to_analysis_response(analysis, db, current_user)
