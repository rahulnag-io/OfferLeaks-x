/**
 * Reconstructed from the API's actual Pydantic response schemas
 * (`apps/api/src/offerleaks/schemas/*.py`, `models/*.py`) -- the
 * original `packages/shared-types` source (presumably hand-written or
 * codegen'd from the OpenAPI schema) was not included in this project
 * backup, only `apps/*`. This file is a faithful reconstruction of the
 * types actually referenced from `apps/web`, kept in sync by hand; if
 * an authoritative generated version of this package exists elsewhere,
 * prefer it over this file.
 */

// --- auth / user (Version 2) ---

export type Role = "user" | "moderator" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
}

export interface TokenResponse {
  user: User;
  access_token: string;
  access_token_expires_at: string;
  refresh_token: string;
  refresh_token_expires_at: string;
  token_type: string;
}

// --- health (Version 1) ---

export interface HealthStatus {
  status: "ok";
  service: string;
  version: string;
}

export interface DependencyHealth {
  database: "ok" | "error";
  redis: "ok" | "error";
}

// --- analyses (Version 3 / M5 history / M6 verdict intelligence / M7 company) ---

export type AnalysisStatus = "pending" | "processing" | "complete" | "failed" | "needs_manual_review";

export type RedFlagSeverity = "low" | "medium" | "high";

export interface RedFlag {
  title: string;
  description: string;
  severity: RedFlagSeverity;
  evidence_quote: string | null;
}

export interface MatchedPattern {
  pattern_key: string;
  title: string;
  severity: RedFlagSeverity;
}

export interface Verdict {
  risk_score: number;
  red_flags: RedFlag[];
  reasoning: string;
  confidence: number;
  created_at: string;
  matched_patterns: MatchedPattern[];
  recommended_actions: string[];
  evidence_coverage: number;
}

// M7: reconstructed here too (rather than only in apps/web's local
// `types/company.ts`) so `Analysis` can carry `company` directly, the
// way it would in the real package -- see that file's docstring for
// why a local duplicate also exists as a stand-in.
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
  advanced: CompanyAdvancedSignals | null;
}

export interface Analysis {
  id: string;
  status: AnalysisStatus;
  file_name: string;
  prompt_version: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  verdict: Verdict | null;
  source_analysis_id: string | null;
  credit_cost: number;
  credit_refunded: boolean;
  company?: CompanyProfile | null;
}

export interface AnalysisListResponse {
  items: Analysis[];
  total: number;
  limit: number;
  offset: number;
}

// --- credits (Version 4) ---

export interface CreditBalance {
  balance: number;
  cost_per_analysis: number;
}

// --- billing / entitlements (M6) ---

export type SubscriptionStatus = "active" | "past_due" | "canceled";

export interface Plan {
  key: string;
  name: string;
  monthly_credit_grant: number;
  monthly_analysis_limit: number | null;
  price_amount_minor: number;
  price_currency: string;
}

export interface Entitlements {
  plan: Plan;
  subscription_status: SubscriptionStatus | null;
  cancel_at_period_end: boolean;
  current_period_end: string | null;
  monthly_analyses_used: number;
  monthly_analysis_limit: number | null;
}

// --- structured reporting + reuse features (M8) ---

export type ReportTargetType = "company" | "offer" | "recruiter" | "website";

export type ReportReason =
  | "upfront_payment_request"
  | "fake_or_unregistered_company"
  | "identity_or_document_theft"
  | "unrealistic_salary_or_offer"
  | "pressure_or_urgency_tactics"
  | "impersonation_of_real_company"
  | "no_interview_or_unverifiable_process"
  | "suspicious_contact_channel"
  | "other";

export type ReportStatus = "submitted" | "under_review" | "verified" | "rejected";

export interface ReportSummary {
  id: string;
  target_type: ReportTargetType;
  status: ReportStatus;
  is_duplicate: boolean;
  created_at: string;
}

export interface ReportDetail extends ReportSummary {
  company_id: string | null;
  analysis_id: string | null;
  target_detail: string | null;
  reasons: ReportReason[];
  description: string;
  updated_at: string;
}

export interface ReportListResponse {
  items: ReportSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ReportCreateRequest {
  target_type: ReportTargetType;
  reasons: ReportReason[];
  description: string;
  company_id?: string | null;
  analysis_id?: string | null;
  target_detail?: string | null;
}

// --- personal analytics (M8) ---

export interface PersonalAnalytics {
  total_analyses: number;
  completed_analyses: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  average_risk_score: number | null;
  distinct_companies_checked: number;
  reports_submitted: number;
}

// --- offer comparison (M8) ---

export interface OfferComparisonItem {
  analysis_id: string;
  file_name: string;
  status: string;
  created_at: string;
  company_name: string | null;
  company_domain: string | null;
  company_verification_status: string | null;
  risk_score: number | null;
  confidence: number | null;
  red_flag_count: number | null;
  matched_pattern_count: number | null;
  recommended_actions: string[];
}

export interface OfferComparison {
  left: OfferComparisonItem;
  right: OfferComparisonItem;
}
