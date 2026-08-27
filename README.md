# OfferLeaks

M8 — Structured Reporting + Reuse Features (private): users can file a structured, private report (company/offer/recruiter/website, categorized reasons, free-text description) directly from the verdict page; reports are never public and never visible to other users. Deterministic (no AI) duplicate detection collapses materially-similar reports about the same company within a configurable window so repeat submissions don't inflate signal. A report only affects anything once an internal reviewer moves it to `verified` — at that point it contributes to the existing M7 `Company` profile as an internal-only reputation signal (never public); a `rejected` report can never contribute. Also ships two free, query-layer reuse features over existing data: personal scam analytics (SQL aggregation, no new schema, free for every plan) and two-offer side-by-side comparison (Pro-gated, no new scoring). See `docs/reports.md`.

M7 — Company Signal & Reputation: each analyzed offer letter now resolves to a shared, cached `Company` profile (domain age, website reachability, email-domain match, and an honest Found/Not Found/Unable-to-verify status) via a free RDAP lookup and a plain outbound reachability check -- no AI calls, no scraping. Cached in Postgres + Redis and reused across every user referencing the same company; refreshed via a dedicated background-worker queue. Basic verification is visible to everyone; advanced signal detail is gated to Pro. See `docs/company_signal.md`.

M6 — Trust Verdict + Monetization Foundation: a rules engine runs alongside the AI verdict to catch known scam patterns deterministically, red flags now carry evidence quotes from the source document, verdicts include rule-based recommended actions, and a Free/Pro plan system (backed by Razorpay subscriptions) gates monthly usage independently of the existing credit system. See `BILLING.md` for the one-time Razorpay setup.

M3 — Upload → OCR → AI Verdict: authenticated users upload an offer letter (PDF/JPEG/PNG), it's malware-scanned and stored, OCR'd via Google Document AI, and analyzed by Claude for fraud risk in a background job — all pollable end-to-end from the frontend.

M2 — Authentication: email/password + Google sign-in via Auth.js, backend-issued JWT access/refresh tokens (independently verified by FastAPI), RBAC scaffold, Redis-backed rate limiting and refresh-token rotation.

See `architecture.md` (milestone 0 planning doc) for the full roadmap and `planning approach.md` for rationale behind every stack choice.

## Stack

- **Monorepo**: Turborepo + npm workspaces (`apps/*`, `packages/*`)
- **Backend**: FastAPI + SQLAlchemy (async) + Alembic, managed with `uv`
- **Frontend**: Next.js (App Router) + TypeScript + Tailwind + Auth.js (NextAuth v5) + TanStack Query
- **Data**: PostgreSQL + Redis
- **Background jobs**: RQ (Redis Queue) — OCR + AI analysis run out-of-band, never inline in a request
- **External providers** (all behind interfaces, see `apps/api/src/offerleaks/providers/`): Cloudflare R2/S3-compatible storage, Google Document AI (OCR), Anthropic/Claude (AI verdicts), ClamAV (malware scanning)

## Prerequisites

- Node.js 20+
- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/) installed
- Docker (for Postgres/Redis/MinIO/ClamAV via `docker-compose`) — or point the corresponding env vars at instances you already have running
- For Version 3's live external calls: an Anthropic API key, a Google Document AI processor (project ID + processor ID + service-account credentials), and an S3-compatible bucket (MinIO locally, or real R2/S3). None of these are required just to run migrations, lint, or the test suite — see "Testing" below.

## First-time setup

```bash
# 1. Install JS/TS dependencies across the whole monorepo
npm install

# 2. Install Python dependencies for the API
cd apps/api && uv sync && cd ../..

# 3. Start Postgres + Redis + MinIO (local S3-compatible storage) + ClamAV
docker compose up -d
# ClamAV can take 1-2 minutes to become healthy on first run while it
# downloads virus definitions -- this is expected.

# 4. Copy env files
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local

# 5. Fill in apps/web/.env.local: generate an AUTH_SECRET (`npx auth secret`),
#    and set INTERNAL_API_SECRET to the same value in both .env files.
#    Google sign-in needs a real AUTH_GOOGLE_ID/AUTH_GOOGLE_SECRET from
#    https://console.cloud.google.com/apis/credentials -- email/password
#    login works fine without them.

# 6. Fill in apps/api/.env for the Version 3 providers you want to exercise
#    live: ANTHROPIC_API_KEY, GOOGLE_DOCUMENT_AI_PROJECT_ID/LOCATION/PROCESSOR_ID
#    (+ GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account key),
#    and STORAGE_* if not using the docker-compose MinIO defaults.

# 7. Run migrations
cd apps/api && uv run alembic upgrade head && cd ../..
```

## Running in development

From the repo root, Turborepo runs both apps in parallel:

```bash
npm run dev
```

- API: http://localhost:8000 (docs at `/docs`)
- Web: http://localhost:3000

The home page shows the Version 1 system-status check plus sign-in/register links. `/register` and `/login` create a session; `/dashboard` is middleware-protected and round-trips through the API's `/users/me` to prove the backend is independently verifying the token, not just trusting the frontend's session. `/dashboard/upload` is Version 3's core loop: upload a document, watch it move through pending → processing → a verdict.

**The background worker is a separate process**, not started by `npm run dev` — run it in another terminal whenever you want uploaded analyses to actually get processed:

```bash
cd apps/api && npm run worker
# equivalent to: uv run python -m offerleaks.worker
```

Without a worker running, `POST /analyses` still succeeds (202, status `pending`) — the job just sits queued in Redis until a worker picks it up.

> **Windows:** RQ's default `Worker` supervises each job in a forked child process, which relies on POSIX-only APIs (`os.fork`, `os.wait4`) that don't exist on native Windows — not even via `SpawnWorker`, which still hits `os.wait4` once it's supervising the spawned child. `npm run worker` auto-detects this and falls back to RQ's `SimpleWorker` on Windows, which runs jobs in-process instead of forking. That's fine for local iteration, but it gives up per-job isolation and RQ's timeout-kill enforcement, so don't rely on it for anything beyond your own dev loop. For the production-faithful behavior (full `Worker`, real isolation) from Windows, run the worker in Docker instead:
>

### Stuck-analysis recovery

The `worker` processes queued analyses. The `reconciler` is a separate long-running
process that periodically checks for analyses stuck in `PENDING` or `PROCESSING`
beyond their timeout, marks them as `FAILED`, and refunds the consumed credit when
applicable. The reconciler runs its recovery loop every 60 seconds.

Start both processes with:

```bash
docker compose --profile worker up -d worker reconciler
````

The `-d` flag runs the containers in the background, so Docker does not attach your
terminal to the live log stream.

#### Watch worker logs live

To watch the worker logs in real time:

```bash
docker compose logs -f worker
```

You should then see output such as:

```text
worker-1  | INFO:rq.worker:Worker ... started with PID ...
worker-1  | ...
worker-1  | Processing job ...
worker-1  | ...
```

The `-f` flag means **follow** — new log lines appear as they happen.

#### Watch worker and reconciler logs

To follow both the worker and reconciler logs:

```bash
docker compose logs -f worker reconciler
```

Or include timestamps:

```bash
docker compose logs -f -t worker reconciler
```

Press `Ctrl+C` to stop following the logs. This only exits the log viewer; it does
not stop the running containers.

#### Reconciler troubleshooting / recovery

If analyses remain stuck in `PENDING` or `PROCESSING`, first verify that the
reconciler service is actually present in the Compose configuration being used.

**1. Check which services Docker Compose sees:**

```bash
docker compose --profile worker config --services
```

The output should include:

```text
postgres
redis
minio
clamav
worker
reconciler
```

If `reconciler` is **not listed**, the Compose file/configuration currently being
used does not define the reconciler service. Check that the `reconciler:` service
exists in the active `docker-compose.yml` and that it is assigned to the expected
`worker` profile. If the Compose file was recently changed, make sure you are
running the command from the correct repository directory and then reload the
services.

**2. If `reconciler` is listed, start it explicitly:**

```bash
docker compose --profile worker up -d reconciler
```

Then verify that both processes are running:

```bash
docker compose --profile worker ps
```

You should see containers similar to:

```text
offerleaks-worker-1       ...   Up
offerleaks-reconciler-1   ...   Up
```

**3. Inspect the reconciler logs:**

```bash
docker compose logs --tail=100 reconciler
```

The reconciler should continue running and periodically process stale analyses.
If it exited or is restarting, inspect the logs for configuration, database, or
Redis connection errors.

**4. Test reconciliation immediately without waiting for the next 60-second cycle:**

The reconciliation command supports a one-shot mode:

```bash
docker compose run --rm reconciler uv run python -m offerleaks.reconciliation --once
```

Use this when diagnosing a genuinely stale analysis. A qualifying stale analysis
should be transitioned to `FAILED`, and the consumed credit should be refunded
through the normal `refund_for_analysis()` recovery path.

After running the one-shot check, inspect the result and logs:

```bash
docker compose logs --tail=100 reconciler
docker compose --profile worker ps
```

Then refresh or re-query the affected analysis from the frontend.

**5. Do not manually refund credits while diagnosing a stuck analysis.**

Reconciliation is designed to make the refund path idempotent, so repeated or
concurrent reconciliation should not double-refund the same analysis. Prefer
letting the production reconciliation code perform the state transition and
refund rather than manually changing the credit balance.

**Quick diagnosis:**

```text
Analysis stuck in PENDING/PROCESSING
        |
        v
docker compose --profile worker config --services
        |
        +-- reconciler missing --> fix active Compose configuration
        |
        +-- reconciler listed
                    |
                    v
        docker compose --profile worker up -d reconciler
                    |
                    v
        docker compose --profile worker ps
                    |
                    +-- reconciler Up --> inspect logs / wait for next cycle
                    |
                    +-- not Up --> docker compose logs --tail=100 reconciler
                    |
                    v
        Need an immediate test?
                    |
                    v
        docker compose run --rm reconciler \
          uv run python -m offerleaks.reconciliation --once
```

## Zrok Tunnel for Payment Testing

The payment flow is handled by the backend for security purposes. Since the payment provider requires the application to be accessible through a public HTTP/HTTPS endpoint, use **zrok2** to expose the local backend running on port `8000`.

### 1. Install and verify zrok2

Check that `zrok2` is installed and available:

```bash
zrok2 --version
```

Check the current zrok2 status:

```bash
zrok2 status
```

### 2. Enable your zrok account

Copy your **enable token** from the zrok web dashboard, then run:

```bash
zrok2 enable "<YOUR_ENABLE_TOKEN>"
```

You only need to do this once per zrok environment.

### 3. Start the public tunnel

Make sure the FastAPI backend is running on port `8000`, then start the tunnel:

```bash
zrok2 share public https://localhost:8000
```

> **Note:** The `https://` URL is used here because the local FastAPI server is expected to be serving HTTPS. If your local backend is actually serving plain HTTP, use:
>
> ```bash
> zrok2 share public http://localhost:8000
> ```

zrok2 will output a public URL. Use that URL wherever the payment provider requires a publicly accessible backend/webhook URL.

The frontend remains available at:

```text
http://localhost:3000
```

while the backend/payment endpoints are exposed through the zrok2 public URL on port `8000`.

### 4. Disable zrok2

When you are finished, disable the zrok environment using:

```bash
zrok2 disable
```

This disables the local zrok environment; it does not delete your zrok account.

## Common commands

Run from the repo root; Turborepo fans these out to every package (including the Python API, via the thin `package.json` wrapper in `apps/api` — see `architecture.md` §0.13):

```bash
npm run lint        # ruff + mypy for the API, eslint for the web app and packages
npm run type-check   # mypy / tsc
npm run test         # pytest for the API
npm run build         # production builds
```

## Testing

The test suite never calls a real external provider (Anthropic, Google Document AI, ClamAV, S3/R2) — `apps/api/tests/analyses/fakes.py` provides in-memory fakes for `StorageProvider`/`OCRProvider`/`AIProvider`/`MalwareScanProvider`, injected via FastAPI's `dependency_overrides` (endpoint tests) or `monkeypatch` (worker tests). Real Postgres and Redis are still used, same convention as Version 2's auth tests — DB constraints and Redis TTL/rotation behavior are real, only the external-provider boundary is faked. This means `npm run test` needs Postgres + Redis running but **not** a configured Anthropic key, Google credentials, or ClamAV daemon.

## Authentication (Version 2)

- **Backend issues its own tokens.** Auth.js orchestrates the login UI (email/password + Google), but the FastAPI backend mints and independently verifies its own short-lived access JWT + rotating refresh JWT on every request — it never trusts Auth.js's session cookie directly. See `apps/api/src/offerleaks/auth/`.
- **RBAC scaffold.** `Role` (`user` / `moderator` / `admin`) exists on every user from this version on, and `require_roles(...)` is ready to gate endpoints, even though nothing but `user` is reachable until Version 8's moderation queue.
- **Rate limiting.** `/auth/*` endpoints are Redis-backed rate-limited per IP (`core/rate_limit.py`).
- **New endpoints**: `POST /auth/register`, `POST /auth/login`, `POST /auth/oauth/google` (server-to-server only, gated by `INTERNAL_API_SECRET`), `POST /auth/refresh`, `POST /auth/logout`, `GET /users/me` (protected).

## Upload → OCR → AI Verdict (Version 3)

- **`POST /analyses`** (multipart, authenticated, rate-limited per-user *and* per-IP): validates the file's real MIME type by magic bytes (not the claimed `Content-Type`) and size, runs it through `MalwareScanProvider` (fails closed — an unreachable scanner rejects the upload, same as an infected one), stores the original in S3-compatible storage, creates an `Analysis` row (`status=pending`), and enqueues a background job. Returns `202` immediately — OCR/AI never run inline in the request.
- **`GET /analyses/{id}`** (authenticated, owner-only — another user's analysis 404s, same no-enumeration principle as the auth endpoints): the frontend polls this. `status` moves `pending` → `processing` → `complete` (with a `verdict`), `failed` (with a generic `error_message`), or `needs_manual_review` if the AI provider errors/times out even after a retry — a fabricated low-confidence verdict is never returned on provider failure.
- **The worker** (`offerleaks.worker`, run via `npm run worker`) does the actual OCR → AI work: downloads the original from storage, extracts text via `OCRProvider` (retried on transient failures), truncates it to a sane length before the AI call, gets a structured `VerdictSchema` back via `AIProvider` (Claude, using tool-calling — never regex-parsed free text), and persists the `Verdict`.
- **Everything vendor-specific is behind an interface** (`apps/api/src/offerleaks/providers/`): swapping OCR/AI/storage/scanning providers is a new class + a config change, not a refactor of the service or worker layer.
- **Frontend**: `/dashboard/upload` never receives the backend's raw access token — the upload form and poller call this app's own same-origin `/api/analyses` routes (`apps/web/src/app/api/analyses/`), which run server-side, read the session via `auth()`, and attach the `Authorization` header themselves before forwarding to the backend.

## Trust Verdict + Monetization Foundation (M6)

- **Rules engine** (`services/rules_engine.py`): deterministic keyword matching against a DB-seeded `scam_patterns` library, run alongside (never instead of) the AI call in `worker.py`. Produces `matched_patterns`, and folds pattern-matched red flags into the same `red_flags` list the AI produces — two independent signals, both persisted on `Verdict`.
- **Evidence highlighting**: `RedFlag.evidence_quote` — the AI is prompted to quote the exact supporting text verbatim per flag where one exists (never fabricated if it doesn't). `Verdict.evidence_coverage` is the fraction of a verdict's flags backed by one, computed server-side.
- **Recommended actions**: `Verdict.recommended_actions` — 2-4 short next-step strings, entirely rule-based (`RulesEngine.recommended_actions_for`) on risk score and flag severity, never AI-generated.
- **Plans & entitlements** (`services/entitlement_service.py`): every user resolves to a `Plan` (Free by default, Pro via an active/past_due `Subscription`). The Free plan's `monthly_analysis_limit` is enforced in `AnalysisService.create_analysis`, independently of (in addition to) the existing Version 4 credit-balance check — see that service's module docstring for why both gates exist.
- **Billing (Razorpay)**: `PaymentProvider` interface + `RazorpayProvider` implementation, `BillingService` for subscribe/cancel/webhook handling, `POST /billing/webhooks/razorpay` for inbound events. Fully idempotent against webhook redelivery and duplicate per-period credit grants — see `BillingService`'s module docstring. **Setup is manual and one-time** — see [`BILLING.md`](./BILLING.md) for the complete Razorpay dashboard walkthrough (API keys, Pro plan creation, webhook configuration) and the `RAZORPAY_*` env vars. Nothing else in the app requires this to be configured.
- **New endpoints**: `GET /billing/plans`, `GET /billing/me`, `POST /billing/subscribe`, `POST /billing/cancel`, `POST /billing/webhooks/razorpay`.
- **Frontend**: `/dashboard/plans` pricing page, a plan/usage indicator on the dashboard, and evidence quotes / recommended actions / matched patterns on the verdict view (`AnalysisSummary`).

## Project layout

```
apps/
  api/            FastAPI backend (src/offerleaks/, layered: routers -> services -> repositories/providers)
    auth/         Token issuance/verification, password hashing, RBAC dependencies -- isolated from services/
    providers/    StorageProvider, OCRProvider, AIProvider, MalwareScanProvider, PaymentProvider -- vendor SDKs never called elsewhere
    prompts/      Versioned AI prompt templates (offer_letter_v1.md, ...)
    worker.py     Background job: OCR -> AI verdict (+ rules engine) for one Analysis (run via `npm run worker`)
  web/            Next.js frontend
    src/auth.ts   Auth.js configuration (Credentials + Google)
    src/app/api/analyses/  Same-origin BFF proxy routes -- the browser never holds the backend access token
    src/app/api/billing/   Same-origin BFF proxy routes for plans/entitlements/subscribe/cancel
packages/
  shared-types/   TypeScript types mirrored with the API's Pydantic schemas
  eslint-config/  Shared ESLint config
  typescript-config/  Shared tsconfig bases
```
