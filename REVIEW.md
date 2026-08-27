# OfferLeaks — Milestone 8 (Structured Reporting + Reuse Features)
## Production-Readiness, Security & Regression Review

**Method note (read first):** This review is based on full static inspection of the actual repository (`m8 - BACKUP.zip`) — models, services, repositories, routers, migrations, schemas, frontend BFF routes/components, and the test suite — cross-checked against `Planning___Architecture.md` and `Revised_ARCHITECTURE.md`. **Live execution was not performed.** The CI workflow provisions real Postgres 16 + Redis 7 service containers and the test fixtures (`TRUNCATE TABLE ... CASCADE`) require a live Postgres instance; neither is available in this environment. Every claim below is either backed by cited code/tests (marked with file:line evidence) or explicitly marked **NOT VERIFIED**. Nothing here should be read as "tests passed" — only "tests exist and, by static reading, assert the right thing."

---

## 1. Original Architecture vs. Actual Implementation

`Revised_ARCHITECTURE.md` §M8 defines M8 as: private structured reporting (company/offer/recruiter/website, categorized reasons, free text), report → internal-only reputation contribution, personal analytics (pure SQL aggregation), 2-offer comparison, no new schema beyond `reports`, no AI/external calls, comparison + detailed reports Pro-gated, basic stats free, founder review via internal tooling instead of a moderator UI.

The actual implementation matches this scope closely:
- One new table (`reports`), two new columns on the existing `company_signals` table. No other schema changes.
- `AnalyticsService` and `ComparisonService` are pure queries over `Analysis`/`Verdict`/`Report` — no new scoring logic, no AI calls, no external integrations (confirmed by grep: no new provider/client imports in either service).
- Report lifecycle (`submitted → under_review → verified/rejected`, terminal `verified`/`rejected`) is implemented as a real, enforced state machine, not just an enum.
- "Founder review via internal tooling" is implemented as `PATCH /reports/{id}/status` gated by `require_roles(Role.ADMIN, Role.MODERATOR)` — reuses the existing RBAC scaffold rather than inventing a moderator system. This matches the architecture doc's explicit instruction not to build moderation UI yet.
- No public report endpoint, no public company-report feed, no report data attached to the shared `CompanyProfileResponse` (confirmed by reading `schemas/company.py` — it has no report or reputation fields).

**Verdict: architecturally faithful.** No scope creep, no premature public surface, no new AI/vendor dependency.

---

## 2. API Inventory

| Method | Route | Auth | Ownership | Purpose | DB Effect | Duplicate Effect | Reputation Effect | Entitlement | Sensitive Fields | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| POST | `/reports` | JWT required | user_id from token | Submit structured report | Insert `Report` | Computes `is_duplicate` at submission | None yet (only VERIFIED counts) | None (open to Free) | description, reasons (private to owner) | Verified in code |
| GET | `/reports/mine` | JWT required | filtered by `user_id` | List own reports (basic shape) | Read | — | — | None (open to Free) | none (summary only) | Verified in code |
| GET | `/reports/{id}` | JWT required | `get_owned_by` (404 if not owner) | Full report detail | Read | — | — | **Pro-gated** (402 for Free) | full description/reasons | Verified in code; frontend never calls this route (see §7.1) |
| PATCH | `/reports/{id}/status` | JWT + `require_roles(ADMIN, MODERATOR)` | N/A (internal) | Transition lifecycle status | Update `Report.status`; conditionally recomputes `CompanySignal` | N/A | Triggers `_recompute_company_reputation` | RBAC only | status | Verified in code; not reachable by `Role.USER` |
| GET | `/analytics/me` | JWT required | `current_user.id` only, no id param exists | Personal stats | Read-only aggregation | — | — | None (free tier) | none (own aggregates only) | Verified in code |
| GET | `/comparison?analysis_id_a&analysis_id_b` | JWT required | both ids independently checked via `get_owned_by` | 2-offer comparison | Read-only | — | — | **Pro-gated** (402 for Free), checked *before* ownership work | offer/verdict fields (own data only) | Verified in code |

Existing endpoints reused unmodified by M8: `POST/GET /analyses`, `GET /analyses/{id}`, `/billing/*`, `/credits/me`, `/auth/*`, `/users/me`. Grep confirms none of these files were touched to add M8-specific branches — `analyses.py`, `billing.py`, `credits.py` contain no `report`/`reputation`/`comparison` references.

---

## 3. Required Security Tests (A–N) — Static Verdict

| Test | Result | Evidence |
|---|---|---|
| A. Cross-user report access | **PASS (by code + test)** | `report_repository.get_owned_by` filters by `user_id`; `test_reports_are_never_exposed_to_another_user` asserts 404 |
| B. Report ownership manipulation | **PASS** | `Report.user_id` is set from `user.id` (the authenticated principal) in `ReportService.submit_report`; `ReportCreateRequest` has no `user_id`/`owner_id` field at all — nothing to manipulate |
| C. Cross-user analytics access | **PASS** | `/analytics/me` takes no id parameter; `AnalyticsService.get_personal_stats(user_id)` is always called with `current_user.id` |
| D. Cross-user offer comparison | **PASS** | `ComparisonService.compare` calls `get_owned_by` independently for both ids and raises a single undifferentiated `OfferNotFoundError` regardless of which one failed — no enumeration; `test_comparison_rejects_another_users_offer_via_api` covers it |
| E. Client company/analysis manipulation | **PASS** | For `target_type=OFFER`, `company_id` is *always* derived server-side from the owned `Analysis.company_id`, never trusted from the request; `test_offer_report_rejects_an_analysis_owned_by_another_user` covers the analysis-ownership half |
| F. Client entitlement manipulation | **PASS** | `test_client_cannot_bypass_pro_gate_via_query_param` explicitly tries `?plan=pro&is_pro=true` against `/reports/{id}` and asserts 402; plan is always resolved from the DB subscription (`EntitlementService.resolve_plan`), never read from the request |
| G. Rejected-report pollution | **PASS (by construction)** | `count_verified_non_duplicate` filters to `status == VERIFIED` only; `REJECTED` is terminal and can never re-enter `VERIFIED`; `test_rejected_report_never_contributes_to_reputation` exists |
| H. Duplicate reputation inflation | **PASS (sequential case only — see §4 for concurrent case)** | `count_verified_non_duplicate` also filters `is_duplicate == False`; `test_duplicate_reports_do_not_double_count_even_if_both_are_verified` covers the sequential path |
| I. Concurrent duplicate submission | **NOT VERIFIED — no test exists, and no locking in code.** See §4 (Concurrency Gaps) |
| J. Invalid status transition | **PASS** | `_ALLOWED_TRANSITIONS` is an explicit whitelist; anything else raises `InvalidStatusTransitionError` → HTTP 409; `test_invalid_status_transition_returns_409` and terminal-state tests exist |
| K. Stored XSS | **PARTIALLY VERIFIED.** Description is stored as plain `Text` via a parameterized ORM insert (no raw SQL) — SQL injection is not a realistic path. Rendering: no `dangerouslySetInnerHTML` exists anywhere the description would be shown (grep confirmed), and there is currently no page that even renders `Report.description` at all (see §7.1), so there's no live XSS surface today — but there is also **no explicit test** asserting safe handling of `<script>`/HTML payloads in the description field, and no sanitization step, so this is unverified for whenever the missing report-detail UI gets built. |
| L. Unauthenticated access | **PASS** | Every M8 route depends on `CurrentUser` (or `require_roles`, which itself depends on it); FastAPI will 401 with no credentials |
| M. Entitlement bypass via direct API (Free user, Pro feature) | **PASS** | Same mechanism as F; both `/reports/{id}` and `/comparison` check `plan_resolution.plan.key != PRO_PLAN_KEY` from DB state before doing any work |
| N. Cache leakage across logout/login | **NOT VERIFIED.** See §4 |

---

## 4. Confirmed Gaps

### 4.1 Concurrency — duplicate-detection race and reputation-recount race (real, unverified)
Two concrete races exist in code, neither covered by a test, neither mitigated by locking:

- **Duplicate-detection race:** `ReportService._detect_duplicate` reads existing reports (`find_recent_for_company`) and decides `is_duplicate` *before* the new row is committed. Two users (or the same user, double-submitting) filing materially identical reports for the same company **concurrently** will each see the other's row as not-yet-existing, and both will be persisted with `is_duplicate=False` — i.e., a duplicate that should have been caught isn't, under true concurrency. This directly maps to Required Test I, which the suite does not implement.
- **Reputation recount race:** `_recompute_company_reputation` does `SELECT COUNT(...) → UPSERT` with no row lock (`SELECT ... FOR UPDATE`) and no serializable isolation. Under Postgres's default READ COMMITTED, two concurrent status transitions to `VERIFIED` for **different reports of the same company**, in **different DB transactions**, can each compute a count that doesn't see the other's not-yet-committed row. Whichever transaction's `UPSERT` commits last **overwrites** `verified_report_count`/`internal_reputation_score` with its own (stale, lower) count — a lost update. This does not cause double-counting (the code's own design goal), but it can cause **undercounting** under concurrent moderation actions.

Given M8's stated low-volume, founder-review usage pattern, the practical exposure is low today, but this is a real correctness gap that should be fixed (row-level lock on `CompanySignal` during recompute, or `SELECT ... FOR UPDATE`) before any moderation volume increases, and a concurrency test should exist regardless of severity.

### 4.2 Frontend: no report-viewing UI exists at all
Grep of the entire `apps/web` tree confirms `listMyReportsUpstream`/`getReportDetailUpstream` (in `lib/api.ts`) and their BFF proxies (`app/api/reports/mine/route.ts`, `app/api/reports/[id]/route.ts`) are **never called from any page or component**. The only frontend report surface is the submission dialog (`report-company-dialog.tsx`). This means:
- The explicit M8 frontend requirement "Pro locked state for detailed reports" has no UI to lock — there is no report-detail page at all, Pro or Free.
- A user cannot see their own submitted reports or their status anywhere in the product, even though the backend fully supports it.
This is a **functional gap**, not a security one — the backend correctly gates and scopes everything it exposes; the feature is simply not wired to a UI.

### 4.3 Frontend: duplicate-report response state is dropped
`ReportCreateRequest`'s response includes `is_duplicate`, but `report-company-dialog.tsx`'s `handleSubmit` only branches on `response.ok`/error — it always shows the same "Report submitted" success message regardless of `is_duplicate`. The explicit roadmap item "duplicate-report response/state where applicable" (frontend scope) is not implemented.

### 4.4 Cache isolation across logout/login — not verified
`QueryProvider` creates a single `QueryClient` via `useState` at the **root layout** (`app/layout.tsx`), which persists for the life of the browser tab unless the component tree remounts. Whether Auth.js's `signOut({ redirectTo })` forces a full page reload (which would remount `QueryProvider` and clear the cache) versus a client-side transition (which would not) determines whether User A's cached `/analytics/me` or `/comparison` responses could render before User B's data arrives after a same-tab logout/login. I could not verify this behavior without a running browser session against the app — flagging as **NOT VERIFIED** rather than assuming either outcome.

### 4.5 No stored-XSS / injection tests
No test in `reports/`, `comparison/`, or `analytics/` submits a payload containing `<script>`, HTML attributes, or SQL/log-injection-shaped strings. Current risk is low only because there is no rendering surface yet (§4.2) and the ORM parameterizes all queries — but this should be tested explicitly, especially before the missing report-detail UI (§4.2) is built, since that is exactly where `description` will first be rendered to a user.

### 4.6 Live execution unverified
Migration execution, the full pytest suite (which requires live Postgres/Redis per `conftest.py`'s `TRUNCATE TABLE ... CASCADE` and `redis_client.flushdb()`), and any true concurrent-request behavior were **not run** in this environment. Everything in §3 marked "PASS" is a static-code-and-test-content verdict, not a confirmed passing test run.

---

## 5. Regression Review (V3–V7)

- **V3 (Upload→OCR→AI verdict):** `analyses.py` router and `analysis_service.py` are untouched by M8 (no report/comparison/analytics imports found in either file). `AnalyticsService`/`ComparisonService` only *read* `Analysis`/`Verdict` rows; neither writes to them. No regression path identified.
- **V4 (Credits):** No M8 file imports `CreditService` or touches `credit_repository.py`/`usage_ledger`. Report submission has its own lightweight per-user rate limit (`rate_limit(key="report_submit", max_attempts=10, window_seconds=300)`) — separate from and does not interact with the credit ledger. No evidence of a second accounting path or credit consumption for reports/analytics/comparison.
- **V5 (Dashboard/history):** M8 adds new pages (`dashboard/analytics`, `dashboard/compare`) alongside, not in place of, `dashboard/history`. `find_recent_for_company`/`count_verified_non_duplicate`/analytics queries all filter defensively (`Analysis.company_id.is_not(None)`, `verdict_row.avg_risk is not None`), which is consistent with graceful handling of old/incomplete records, though this was **not tested against actual pre-M7 production data** (only fixture data in unit tests).
- **V6 (Entitlements):** `EntitlementService` is reused as-is (no new entitlement service created); M8 adds no new columns or methods to it. Verdict access itself remains ungated — only comparison and detailed-report *viewing* are gated, matching M6's principle that base product value isn't paywalled.
- **V7 (Company reputation):** `set_report_reputation_signal` updates only the two new columns via a scoped `UPSERT`, explicitly avoiding touching `domain_age`/`website_reachability`/`email_domain_match` columns owned by M7 (confirmed by reading the statement's `set_={...}` dict, which lists only the two M8 columns). Company identity (`company_id`) is never mutated by M8 code.

No regressions identified in static review; none of this was exercised end-to-end against live data.

---

## 6. Missing / Incomplete Items, by Severity

**HIGH**
- No UI surface for viewing submitted reports or their detail/Pro-lock state (§4.2) — an explicit roadmap frontend deliverable is absent.
- Concurrent-submission and concurrent-status-transition races are real and untested (§4.1).

**MEDIUM**
- Duplicate-state UX not implemented in the report dialog (§4.3).
- No stored-XSS/injection test coverage for free-text report fields (§4.5).
- Cache-isolation-after-logout behavior unverified (§4.4).

**LOW**
- No end-to-end (browser-driven) test walking upload → verdict → report → duplicate → analytics → comparison as one flow; coverage is per-layer (service + endpoint), not full-journey.
- No explicit test for Unicode/punctuation-only duplicate-detection edge cases, though `normalize_report_text`'s regex-based approach handles them by construction.

**Not flagged (explicitly deferred per architecture, correctly not built):** public report visibility, moderator UI/roles, Scam Wall pipeline, embeddings/AI-based duplicate detection, reputation trend history.

---

## 7. Architectural Risks Heading Into Version 9+

- The reputation-recompute race (§4.1) will matter more once report volume grows past "founder reviews it by hand" — worth fixing before any moderation-queue UI (M10) is built on top of `verified_report_count`.
- `find_recent_for_company` scans all non-duplicate reports for a company since the window start with no upper bound on window size or candidate count — fine at current volume, but the `SequenceMatcher` comparison is O(n) per candidate and O(n²) if a company accumulates many reports in one window; worth a cap before Scam Wall-scale volume.
- The complete absence of a report-viewing UI means the "personal report history" experience users will expect by V9 doesn't exist yet — this is product debt, not architecture debt, but it's on the critical path for whatever V9 builds on top of user-visible report state.

---

## 8. Recommended Fixes Before Proceeding (Minimum Set)

1. Add row-level locking (`SELECT ... FOR UPDATE` on the `CompanySignal` row) around `_recompute_company_reputation`, or serialize it behind the same atomic-UPDATE discipline used elsewhere, and add a concurrency test.
2. Build the missing "My Reports" list/detail UI (even minimal), including the Pro-locked state for detail and the duplicate-state UX in the submission dialog.
3. Add explicit stored-XSS/injection tests for `description`/`target_detail`, especially before the detail UI in (2) ships.
4. Verify (via an actual browser session, not code reading) that logout clears the TanStack Query cache before another user logs in on the same device.
5. Run the actual test suite and a live migration against a real Postgres/Redis instance — this review's "PASS" verdicts are static-code verdicts, not confirmed test runs.

---

## 9. Overall Readiness Score: **72%**

Breakdown: authorization/IDOR/ownership and reputation-integrity logic are strong and well-tested at the unit/HTTP layer (this pulls the score up significantly) — but two real, unaddressed concurrency bugs, a materially incomplete frontend (no report-viewing surface at all), and zero live-execution verification are not minor deductions. The score reflects "the hard part (server-side authorization and data integrity discipline) was done carefully" offset by "several explicitly-scoped deliverables are unfinished or unverified."

## 10. Final Decision

**READY FOR VERSION 9 WITH REQUIRED FIXES**

Rationale: there is no evidence of the disqualifying failure modes this review was designed to catch — no cross-user report/analytics/offer leakage, no client-controlled ownership or entitlement bypass, no rejected-report reputation pollution, no sequential duplicate-reputation inflation, no major regression to V3–V7, and no destructive migration. Those are exactly the conditions that would mandate NOT READY. What remains (the reputation-recompute race, the missing report-viewing UI, and unverified live execution) are real but bounded and fixable without re-architecting M8, which is what distinguishes "with required fixes" from "not ready."
