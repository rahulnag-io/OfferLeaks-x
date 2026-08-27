import type { AnalysisStatus, RedFlagSeverity } from "@offerleaks/shared-types";

export type RiskLevel = "low" | "medium" | "high";

/**
 * Maps the backend's 0-100 risk_score onto three risk bands. Purely a
 * presentation grouping -- the underlying number from the verdict is
 * always shown too, never replaced by the label alone.
 */
export function getRiskLevel(score: number): RiskLevel {
  if (score < 34) return "low";
  if (score < 67) return "medium";
  return "high";
}

export const RISK_LEVEL_COPY: Record<RiskLevel, { label: string; hint: string }> = {
  low: { label: "Low risk", hint: "Few or no scam indicators found" },
  medium: { label: "Medium risk", hint: "Some indicators worth a closer look" },
  high: { label: "High risk", hint: "Multiple strong scam indicators found" },
};

export const RISK_LEVEL_BADGE_VARIANT: Record<RiskLevel, "safe" | "caution" | "risk"> = {
  low: "safe",
  medium: "caution",
  high: "risk",
};

// Tailwind color tokens (as HSL var names, for use in inline styles like
// the conic-gradient risk gauge, which can't consume Tailwind classes).
export const RISK_LEVEL_GAUGE_VAR: Record<RiskLevel, string> = {
  low: "var(--safe)",
  medium: "var(--caution)",
  high: "var(--risk)",
};

export const SEVERITY_BADGE_VARIANT: Record<RedFlagSeverity, "safe" | "caution" | "risk"> = {
  low: "safe",
  medium: "caution",
  high: "risk",
};

export const SEVERITY_LABEL: Record<RedFlagSeverity, string> = {
  low: "Minor",
  medium: "Notable",
  high: "Serious",
};

export const STATUS_LABEL: Record<AnalysisStatus, string> = {
  pending: "Queued",
  processing: "Analyzing",
  complete: "Complete",
  failed: "Failed",
  needs_manual_review: "Needs review",
};

export const STATUS_BADGE_VARIANT: Record<AnalysisStatus, "default" | "secondary" | "safe" | "caution" | "risk"> = {
  pending: "secondary",
  processing: "default",
  complete: "safe",
  failed: "risk",
  needs_manual_review: "caution",
};

export const IN_PROGRESS_STATUSES: readonly AnalysisStatus[] = ["pending", "processing"];
export const TERMINAL_STATUSES: readonly AnalysisStatus[] = ["complete", "failed", "needs_manual_review"];
