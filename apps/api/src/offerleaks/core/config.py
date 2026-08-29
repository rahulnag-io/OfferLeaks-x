"""Application configuration.

Single source of truth for environment-derived settings. Every other
module reads config through `get_settings()` rather than `os.environ`
directly, so tests can override settings by dependency-injecting a
different `Settings` instance instead of mutating process env vars.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "OfferLeaks API"
    app_version: str = "0.1.0"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # --- CORS ---
    # The web app origin(s) allowed to call this API from the browser.
    # Comma-separated in the env var, parsed into a list here.
    cors_origins: str = Field(default="http://localhost:3000")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://offerleaks:offerleaks_dev@localhost:5432/offerleaks"
    )

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Auth (Version 2) ---
    # Signs/verifies the API's own access & refresh JWTs. Independent of
    # whatever session mechanism the frontend uses (see architecture.md
    # §0.13) -- the backend never trusts a token it didn't mint and verify
    # itself.
    jwt_secret_key: str = Field(
        default="dev-only-insecure-secret-change-me-in-production-please"
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_issuer: str = Field(default="offerleaks-api")
    access_token_expire_minutes: int = Field(default=15)
    refresh_token_expire_days: int = Field(default=30)

    # Shared secret the Next.js server presents when calling the
    # OAuth-upsert endpoint on the user's behalf. This endpoint creates/logs
    # in a user from a provider-asserted identity with no password check, so
    # it must only be reachable from a trusted server, never a browser.
    internal_api_secret: str = Field(default="dev-only-internal-secret-change-me")

    # --- Rate limiting ---
    # Redis-backed, applied per-IP to the auth endpoints first (§0.11) --
    # the same abstraction gets reused for the upload/analysis endpoint in
    # Version 3.
    rate_limit_auth_attempts: int = Field(default=10)
    rate_limit_auth_window_seconds: int = Field(default=60)

    # Version 3's upload endpoint is the most expensive/abuse-prone route
    # (§0.11), so it's rate-limited harder than auth, and per-user *and*
    # per-IP (the Version 2 review's Low-severity finding: auth-only
    # rate limiting was per-IP because there's no authenticated user yet
    # at login time; upload has one, so both keys apply here).
    rate_limit_upload_attempts: int = Field(default=5)
    rate_limit_upload_window_seconds: int = Field(default=300)

    # --- Object storage (Version 3) ---
    # S3-compatible (Cloudflare R2 at MVP per architecture.md §0.4/§0.10).
    # Original uploaded offer letters live here, never in Postgres.
    storage_endpoint_url: str = Field(default="http://localhost:9000")
    storage_bucket: str = Field(default="offerleaks-uploads-dev")
    storage_access_key_id: str = Field(default="dev-only-access-key")
    storage_secret_access_key: str = Field(default="dev-only-secret-key")
    storage_region: str = Field(default="auto")
    # How long a generated download URL (used by workers/OCR, never handed
    # to the browser directly) stays valid.
    storage_signed_url_expire_seconds: int = Field(default=300)

    # --- OCR provider (Version 3) ---
    # Google Document AI, behind the `OCRProvider` interface (§0.13) --
    # nothing outside `providers/ocr.py` imports this SDK directly.
    google_document_ai_project_id: str = Field(default="")
    google_document_ai_location: str = Field(default="us")
    google_document_ai_processor_id: str = Field(default="")
    # Standard Google client-library env var (GOOGLE_APPLICATION_CREDENTIALS)
    # is read directly by the SDK, not duplicated here.

    # --- AI provider (Version 3) ---
    # Claude, behind the `AIProvider` interface (§0.6) -- swapping to
    # GPT/Gemini later is a new provider class + a config change, not a
    # rewrite of anything that calls `AIProvider.analyze_offer_letter`.
    anthropic_api_key: str = Field(default="")
    ai_model: str = Field(default="claude-sonnet-5")
    ai_prompt_version: str = Field(default="offer_letter_v1")
    # OCR text is truncated to this many characters before it's sent to
    # the model -- you don't pay to send a 40-page PDF's whitespace
    # through the API (§0.6 cost optimization).
    ai_max_input_characters: int = Field(default=40_000)
    ai_request_timeout_seconds: float = Field(default=60.0)

    # --- Malware scanning (Version 3) ---
    # Cloudmersive's hosted Virus Scan API, reached over HTTPS -- gates
    # every upload before it's persisted or handed to the OCR provider
    # (§0.11 "file upload safety"). Previously ClamAV via a self-hosted
    # `clamd` daemon; moved to a hosted scanner because `clamd`'s loaded-
    # signature-database memory footprint doesn't fit alongside the API
    # process on Render's 512MB free/Starter tier (see malware_scan.py's
    # module docstring). Disabled only for local dev when no key is
    # configured; production must never run with this off (enforced in
    # `require_production_config` below, not just documented here).
    malware_scan_enabled: bool = Field(default=True)
    cloudmersive_api_key: str = Field(default="")
    cloudmersive_request_timeout_seconds: float = Field(default=30.0)

    # --- Upload constraints (Version 3) ---
    max_upload_size_bytes: int = Field(default=15 * 1024 * 1024)  # 15 MB
    allowed_upload_mime_types: str = Field(
        default="application/pdf,image/jpeg,image/png"
    )

    # Background job queue (Redis-backed, per §0.7/§0.8) that OCR + AI
    # analysis run on -- never inline in the request/response cycle.
    analysis_queue_name: str = Field(default="analyses")
    # RQ's own hard per-job ceiling (fork-based `Worker` kills the job's
    # work-horse process if it runs longer than this -- see worker.py's
    # `_run_worker` docstring). Previously hardcoded as the string "10m"
    # at both `get_analysis_queue().enqueue(...)` call sites; centralized
    # here because `processing_analysis_timeout_seconds` below must stay
    # safely above it (see that field's docstring) -- two independent
    # hardcoded copies of "10 minutes" is exactly the kind of drift that
    # would quietly break that invariant.
    analysis_job_timeout_seconds: int = Field(default=600)  # 10 minutes

    # M7: separate queue/timeout for company-profile refresh jobs -- see
    # `core/queue.py::get_company_queue`'s docstring for why this is
    # independent of the analysis queue.
    company_refresh_queue_name: str = Field(default="company_refresh")
    company_refresh_job_timeout_seconds: int = Field(default=60)

    # --- Stuck-analysis recovery ---
    # A PENDING analysis older than this is almost certainly a job that
    # was never picked up by any worker (no worker process running, or
    # the enqueue call succeeded but something's wrong downstream) --
    # normal Redis/RQ dispatch latency is milliseconds, so 5 minutes is
    # already a generous margin before treating it as stuck.
    pending_analysis_timeout_seconds: int = Field(default=300)  # 5 minutes
    # Deliberately *not* keyed off a worker heartbeat: RQ's fork-based
    # `Worker` already enforces `analysis_job_timeout_seconds` as a hard
    # per-job ceiling, independent of this application's own code (it
    # kills the work-horse process even if it's wedged in a way that
    # would never reach our own exception handling -- exactly the "worker
    # gets stuck, crashes, or times out" scenario this feature exists
    # for). A PROCESSING analysis older than that ceiling, plus a safety
    # margin, can therefore only be one of: a crashed/killed worker
    # process, a job RQ already force-killed, or a `SimpleWorker` (no
    # timeout enforcement -- Windows-local-dev only, see worker.py)
    # genuinely wedged. None of those are "still legitimately running,"
    # so no heartbeat is needed to tell them apart from one that is.
    # Default is `analysis_job_timeout_seconds` (10 min) + 5 min margin
    # to absorb the reconciliation sweep's own polling interval and
    # reasonable worst-case latency around the moment RQ kills a job.
    processing_analysis_timeout_seconds: int = Field(default=900)  # 15 minutes
    # How often the reconciliation sweep runs (`offerleaks/reconciliation.py`).
    # Frequent enough to keep detection lag small relative to the
    # multi-minute timeouts above; infrequent enough not to add
    # meaningful load to Postgres.
    reconciliation_interval_seconds: int = Field(default=60)
    # Caps how many stuck analyses one sweep will claim, bounding
    # worst-case work per iteration. If a real deployment ever
    # legitimately exceeds this in one window, that's itself a signal of
    # a bigger outage; the next sweep (a minute later, by the default
    # above) picks up whatever's left.
    reconciliation_batch_size: int = Field(default=100)

    # --- Credits (Version 4) ---
    # Both are server-side only -- the client never supplies or overrides
    # either value (architecture.md §0.2's "credits gate AI cost exposure").
    # Free credits granted once, server-side, the moment a user account is
    # created (registration or first OAuth sign-in).
    credit_initial_grant: int = Field(default=3)
    # Cost of one analysis, in credits. A config change here changes the
    # price for every *new* analysis; it never retroactively changes what
    # was already charged (ledger entries record the amount at charge time).
    credit_cost_per_analysis: int = Field(default=1)

    # --- Billing / Razorpay (M6: Trust Verdict + Monetization Foundation) ---
    # All three are required to actually create/cancel subscriptions or
    # verify webhook signatures (`RazorpayProvider` raises a typed
    # `PaymentPermanentError` at call time if unset -- not at import time,
    # so the app still boots and every non-billing route works with these
    # unset, same "optional locally" posture as the other provider keys
    # above). See the M6 billing integration guide (BILLING.md) for how
    # to obtain each of these from the Razorpay dashboard.
    razorpay_key_id: str = Field(default="")
    razorpay_key_secret: str = Field(default="")
    # HMAC secret configured against the specific webhook endpoint in the
    # Razorpay dashboard (Settings -> Webhooks) -- deliberately a
    # *different* secret than `razorpay_key_secret`, matching Razorpay's
    # own separation between "API auth" and "webhook signing." Required
    # to verify `POST /billing/webhooks/razorpay` requests actually came
    # from Razorpay (architecture.md §0.11).
    razorpay_webhook_secret: str = Field(default="")
    # How long a `PaymentProvider` HTTP call to Razorpay's API waits
    # before being treated as a transient failure (retried by the caller
    # per §0.6's provider fallback posture -- same shape as
    # `ai_request_timeout_seconds`/OCR's own timeout).
    razorpay_request_timeout_seconds: float = Field(default=15.0)

    # --- Company signal & reputation (M7: lean version) ---
    # Free RDAP (Registration Data Access Protocol) lookup for domain age
    # -- no API key required, no vendor SDK. Wrapped behind
    # `DomainAgeProvider` (providers/domain_age.py) the same way OCR/AI
    # are behind their own interfaces, so a paid WHOIS vendor can replace
    # it later without touching `CompanyProfileService`.
    rdap_base_url: str = Field(default="https://rdap.org/domain")
    domain_age_request_timeout_seconds: float = Field(default=8.0)
    # Separate from the domain-age timeout: reachability is a plain HTTP
    # HEAD/GET against the company's own site, not a third-party API.
    website_reachability_timeout_seconds: float = Field(default=6.0)

    # A cached profile older than this is "stale" and eligible for a
    # background refresh (via the existing RQ worker) the next time it's
    # read -- it is still served as-is in the meantime (M7 DoD: a cache
    # hit never blocks on a second external lookup).
    company_profile_stale_after_seconds: int = Field(
        default=7 * 24 * 60 * 60
    )  # 7 days
    # Redis acceleration layer TTL for a company profile. Deliberately
    # shorter than the Postgres staleness window above: Redis is free to
    # forget sooner (Postgres is authoritative and always repopulates it
    # on a cache miss, per M7's "cache survives restarts" requirement),
    # this just bounds how long a Redis-only cache entry lives before a
    # read falls back to Postgres.
    company_profile_redis_ttl_seconds: int = Field(
        default=24 * 60 * 60
    )  # 1 day

    # Cost control (M7 §17): caps how many outbound domain-age/reachability
    # lookups the whole system will perform per minute, independent of how
    # many users or analyses trigger them -- caching is the primary cost
    # control (one lookup serves every user of that company), this is a
    # backstop against a burst of first-time/never-cached companies.
    company_lookup_rate_limit_per_minute: int = Field(default=20)
    # How long a per-company lookup lock is held while a resolution/
    # refresh is in flight, so two concurrent requests for the same
    # brand-new company don't both dispatch external calls (M7 DoD:
    # "two users uploading offers from the same company... without
    # triggering a second external lookup").
    company_lookup_lock_seconds: int = Field(default=30)

    # --- Structured reporting (M8: Structured Reporting + Reuse Features) ---
    # Two reports about the *same company* with a "materially similar"
    # (see `services/report_duplicate_detection.py`) description filed
    # within this many hours of each other are treated as one duplicate
    # complaint for reputation-counting purposes, not two independent
    # ones. 30 days: long enough to catch the common case of several
    # people reporting the same live scam campaign in quick succession,
    # short enough that a genuinely new incident against the same
    # (possibly previously-legitimate) company much later isn't
    # incorrectly suppressed as a duplicate of stale history.
    report_duplicate_window_hours: int = Field(default=24 * 30)
    report_duplicate_similarity_threshold: float = Field(default=0.72)
    # How many verified (non-duplicate) reports it takes to reach the top
    # of the internal 0-100 concern score
    # (`ReportService._reputation_score_for`) -- deliberately a small
    # number: this is a low-volume, early-stage signal (M8 §"Cost":
    # "effectively zero marginal cost," not a statistically-robust
    # aggregate yet), so a handful of verified reports should already
    # read as meaningfully concerning internally, long before public
    # reputation surfacing (M10) would ever need a sturdier curve.
    report_reputation_score_saturation_count: int = Field(default=5)

    @property
    def billing_configured(self) -> bool:
        return bool(
            self.razorpay_key_id
            and self.razorpay_key_secret
            and self.razorpay_webhook_secret
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def allowed_upload_mime_type_set(self) -> set[str]:
        return {
            t.strip()
            for t in self.allowed_upload_mime_types.split(",")
            if t.strip()
        }

    def require_production_config(self) -> None:
        """Fail fast on boot if a deployed (non-development) environment is
        missing config that only has safe defaults for local dev.

        Distinguishes "optional locally, required in production" (§0.9) --
        `Settings()` itself stays constructible with dev-only placeholders
        so tests and local dev never need every provider credential set.
        """
        if self.environment == "development":
            return

        missing: list[str] = []
        if not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.google_document_ai_project_id:
            missing.append("GOOGLE_DOCUMENT_AI_PROJECT_ID")
        if not self.google_document_ai_processor_id:
            missing.append("GOOGLE_DOCUMENT_AI_PROCESSOR_ID")
        if self.storage_access_key_id == "dev-only-access-key":
            missing.append("STORAGE_ACCESS_KEY_ID")
        if self.storage_secret_access_key == "dev-only-secret-key":
            missing.append("STORAGE_SECRET_ACCESS_KEY")
        if self.jwt_secret_key == "dev-only-insecure-secret-change-me-in-production-please":
            missing.append("JWT_SECRET_KEY")
        if not self.malware_scan_enabled:
            missing.append("MALWARE_SCAN_ENABLED (must be true outside development)")
        elif not self.cloudmersive_api_key:
            missing.append("CLOUDMERSIVE_API_KEY")

        # Billing is all-or-nothing: a production deploy with *some* but
        # not all three Razorpay values set is almost certainly a
        # misconfiguration (a partially-copied .env, a forgotten webhook
        # secret) rather than an intentional "billing disabled" choice --
        # fail loud rather than silently accept subscriptions with
        # webhook verification impossible.
        razorpay_fields = {
            "RAZORPAY_KEY_ID": self.razorpay_key_id,
            "RAZORPAY_KEY_SECRET": self.razorpay_key_secret,
            "RAZORPAY_WEBHOOK_SECRET": self.razorpay_webhook_secret,
        }
        set_fields = [name for name, value in razorpay_fields.items() if value]
        if set_fields and len(set_fields) < len(razorpay_fields):
            missing.extend(
                name for name in razorpay_fields if not razorpay_fields[name]
            )

        if missing:
            raise RuntimeError(
                "Missing required production configuration: " + ", ".join(missing)
            )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton.

    lru_cache keeps this a true singleton per-process while still being
    overridable in tests via FastAPI's dependency_overrides.
    """
    return Settings()
