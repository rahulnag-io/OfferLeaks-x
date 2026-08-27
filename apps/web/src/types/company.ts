/**
 * M7 (Company Signal & Reputation) response types.
 *
 * These belong in `@offerleaks/shared-types` alongside `Analysis`,
 * `MatchedPattern`, etc. (the same workspace package every other
 * backend-response type in this app is imported from) -- but that
 * package isn't part of this project backup, so `Analysis` itself
 * can't be extended with a `company` field at its source. Declared
 * locally here instead, as the smallest non-invasive stand-in:
 * `AnalysisWithCompany` intersects the real `Analysis` type with the
 * one field M7 actually adds to `GET /analyses/{id}`. When
 * `@offerleaks/shared-types` is available again, `company` should move
 * onto `Analysis` there and this file's `AnalysisWithCompany` alias can
 * be deleted in favor of the real `Analysis` type directly.
 */

import type { Analysis } from "@offerleaks/shared-types";

export type CompanyVerificationStatus = "found" | "not_found" | "insufficient_evidence";

export interface CompanyAdvancedSignals {
  domain_age_days: number | null;
  website_reachable: boolean | null;
  email_domain_match: boolean | null;
}

export interface CompanyProfile {
  company_name: string | null;
  domain: string | null;
  verification_status: CompanyVerificationStatus;
  last_checked_at: string;
  // `null` for a Free user (gated out server-side) -- see
  // `apps/api/.../api/routers/analyses.py::_build_company_response`.
  advanced: CompanyAdvancedSignals | null;
}

export type AnalysisWithCompany = Analysis & { company?: CompanyProfile | null };
