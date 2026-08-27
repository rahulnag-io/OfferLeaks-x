# Milestone 8: Structured Reporting + Reuse Features

Private, structured user reports that feed an internal-only signal on
top of M7's company profile, plus two free-standing "reuse" features
over data the product already has: personal analytics and two-offer
comparison. No AI calls, no new external integrations, no public
surface.

## Reports

A report is `target_type` (`company` / `offer` / `recruiter` /
`website`), one or more categorized `reasons`, and a free-text
`description`. It is **always private**: never visible to any user
other than the one who filed it, never listed anywhere public, and
there is no moderator UI in this milestone -- founder review happens
through internal tooling (`PATCH /reports/{id}/status`, gated to
`admin`/`moderator` roles) or direct DB queries.

Reporting an `offer` reuses that analysis's already-resolved company
context (`ReportService.submit_report`) rather than asking the user to
re-identify the company -- a client-supplied `company_id` is never
trusted over the offer's own resolution.

### Status lifecycle

```
submitted --> under_review --> verified
          \--> under_review --> rejected
          \--> verified
          \--> rejected
```

`verified` and `rejected` are **terminal** -- once decided, a report
never transitions again. This is what makes "a rejected report can
never silently pollute the internal reputation score" hold
structurally, not just by convention: only `verified` is ever eligible,
and once a report reaches `verified` or `rejected` there is no path back
out of it.

### Duplicate detection

Deterministic, no AI: a new report's description is normalized
(lowercase, punctuation stripped, whitespace collapsed --
`services/report_duplicate_detection.py`) and compared via
`difflib.SequenceMatcher` against other reports for the *same company*
filed within a configurable window (`report_duplicate_window_hours`,
default 30 days). Above `report_duplicate_similarity_threshold`
(default 0.72), the new report is flagged `is_duplicate=True`.

A flagged duplicate is **still stored** -- every submission a user makes
is a truthful, auditable record -- but it is permanently excluded from
the internal reputation count regardless of what status it's later
moved to.

### Internal reputation signal

Extends the M7 `CompanySignal` row (does not create a second/competing
reputation table): `verified_report_count` and `internal_reputation_score`
(a deterministic 0-100 concern score). Both are recomputed via a **full
re-count** of `reports` (`WHERE status = 'verified' AND is_duplicate =
false`) every time a report's status changes, never an incremental
+1/-1 -- so re-running the recompute after a retry or repeated
processing always converges on the same correct number rather than
compounding an error.

**Neither field is ever exposed in the public company API** --
`schemas/company.py::CompanyProfileResponse` does not include them. This
is a product signal for future use (M9+), not a public score.

## Personal analytics

`GET /analytics/me` -- pure SQL aggregation (`services/analytics_service.py`)
over the user's own `Analysis`/`Verdict`/`Report` rows. No new schema,
no AI, free for every plan. Every query is scoped to `user_id` in the
`WHERE`/`JOIN` itself.

## Offer comparison

`GET /comparison?analysis_id_a=...&analysis_id_b=...` -- Pro-gated,
query-layer only (`services/comparison_service.py`), no new scoring. A
"saved offer" is simply the user's own `Analysis`; ownership is checked
independently for both ids before any data is returned.

## Billing

- Basic personal statistics: **free**, every plan.
- Offer comparison: **Pro-gated**, enforced server-side
  (`api/routers/comparison.py`) via `EntitlementService`.
- Detailed report view (`GET /reports/{id}`, full reasons/description):
  **Pro-gated**. `POST /reports` (submission) and `GET /reports/mine`
  (basic list: id/target_type/status/created_at) remain available to
  every plan.

None of these gates can be bypassed via request parameters -- the plan
is always resolved server-side from subscription state.
