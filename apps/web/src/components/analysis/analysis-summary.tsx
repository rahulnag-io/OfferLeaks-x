import type { Verdict } from "@offerleaks/shared-types";

import { ConfidenceIndicator } from "@/components/analysis/confidence-indicator";
import { RecommendedActions } from "@/components/analysis/recommended-actions";
import { RedFlagList } from "@/components/analysis/red-flag-list";
import { RiskScoreRing } from "@/components/analysis/risk-score";
import { VerdictIntelligence } from "@/components/analysis/verdict-intelligence";
import { Separator } from "@/components/ui/separator";

/**
 * Full verdict presentation -- risk score, confidence, reasoning, red
 * flags, and (M6) recommended actions and verdict-intelligence signals.
 * Only ever renders fields that exist on the backend's Verdict schema;
 * nothing here is invented.
 */
export function AnalysisSummary({ verdict }: { verdict: Verdict }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <div className="flex shrink-0 flex-col items-center gap-3 sm:w-48">
          <RiskScoreRing score={verdict.risk_score} />
          <ConfidenceIndicator confidence={verdict.confidence} />
        </div>

        <Separator orientation="vertical" className="hidden self-stretch sm:block" />
        <Separator className="sm:hidden" />

        <div className="flex flex-1 flex-col gap-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">What we found</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{verdict.reasoning}</p>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-foreground">Red flags</h3>
            <RedFlagList flags={verdict.red_flags} />
          </div>
        </div>
      </div>

      <RecommendedActions actions={verdict.recommended_actions} />

      <VerdictIntelligence
        matchedPatterns={verdict.matched_patterns}
        evidenceCoverage={verdict.evidence_coverage}
      />
    </div>
  );
}
