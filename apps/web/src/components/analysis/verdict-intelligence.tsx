import type { MatchedPattern } from "@offerleaks/shared-types";
import { ScanSearch } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { SEVERITY_BADGE_VARIANT } from "@/lib/risk";

/**
 * M6: two independent, deterministic signals surfaced alongside the AI's
 * own verdict (`AnalysisSummary`) -- never merged into its prose, so a
 * user can tell "the model said X" apart from "our pattern library
 * matched Y" and "this many of the flags above are backed by an exact
 * quote."
 */
export function VerdictIntelligence({
  matchedPatterns,
  evidenceCoverage,
}: {
  matchedPatterns: MatchedPattern[];
  evidenceCoverage: number;
}) {
  const coveragePercent = Math.round(evidenceCoverage * 100);

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <ScanSearch className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
            Evidence coverage
          </h3>
          <span className="text-sm font-medium text-foreground">{coveragePercent}%</span>
        </div>
        <Progress value={coveragePercent} />
        <p className="mt-1.5 text-xs text-muted-foreground">
          Share of the flags above backed by an exact quote from the document.
        </p>
      </div>

      {matchedPatterns.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-foreground">
            Known scam patterns detected
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {matchedPatterns.map((pattern) => (
              <Badge key={pattern.pattern_key} variant={SEVERITY_BADGE_VARIANT[pattern.severity]}>
                {pattern.title}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
