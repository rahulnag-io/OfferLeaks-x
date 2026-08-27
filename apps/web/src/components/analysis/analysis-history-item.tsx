"use client";

import type { Analysis } from "@offerleaks/shared-types";
import { useState } from "react";
import { ChevronDown, FileText, RotateCw } from "lucide-react";

import { AnalysisStatusBadge } from "@/components/analysis/status-badge";
import { RedFlagList } from "@/components/analysis/red-flag-list";
import { RiskScoreBar } from "@/components/analysis/risk-score";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { TERMINAL_STATUSES } from "@/lib/risk";
import { cn } from "@/lib/utils";

export function AnalysisHistoryItem({
  analysis,
  onRecheckSucceeded,
  readOnly = false,
}: {
  analysis: Analysis;
  onRecheckSucceeded?: () => void;
  /** Hides the re-check action -- for read-only summaries (e.g. the dashboard's recent-activity teaser) that have no query to invalidate on success. */
  readOnly?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [isRechecking, setIsRechecking] = useState(false);
  const [recheckError, setRecheckError] = useState<string | null>(null);

  const canRecheck =
    !readOnly && TERMINAL_STATUSES.includes(analysis.status);

  // Fixed locale and timezone prevent server/client hydration mismatches.
  const createdAt = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  }).format(new Date(analysis.created_at));

  async function handleRecheck() {
    setRecheckError(null);
    setIsRechecking(true);

    try {
      const response = await fetch(`/api/analyses/${analysis.id}/recheck`, {
        method: "POST",
      });

      const body = (await response.json().catch(() => null)) as
        | Analysis
        | { detail?: string }
        | null;

      if (!response.ok) {
        const detail = body && "detail" in body ? body.detail : undefined;
        setRecheckError(detail ?? `Re-check failed: ${response.status}`);
        return;
      }

      onRecheckSucceeded?.();
    } catch {
      setRecheckError("Could not reach the server. Please try again.");
    } finally {
      setIsRechecking(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-subtle sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
            <FileText className="h-4 w-4" strokeWidth={1.75} />
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium text-foreground">
                {analysis.file_name}
              </span>

              <AnalysisStatusBadge status={analysis.status} />

              {analysis.source_analysis_id && (
                <Badge variant="outline">Re-check</Badge>
              )}
            </div>

            <p className="mt-1 text-xs text-muted-foreground">
              {createdAt} ·{" "}
              {analysis.credit_cost === 0
                ? "Free"
                : `${analysis.credit_cost} credit${
                    analysis.credit_cost === 1 ? "" : "s"
                  }`}
              {analysis.credit_refunded && " (refunded)"}
            </p>

            {analysis.status === "failed" && analysis.error_message && (
              <p className="mt-1.5 text-xs text-risk-foreground">
                {analysis.error_message}
              </p>
            )}

            {analysis.status === "needs_manual_review" &&
              analysis.error_message && (
                <p className="mt-1.5 text-xs text-caution-foreground">
                  {analysis.error_message}
                </p>
              )}

            {recheckError && (
              <p className="mt-1.5 text-xs text-risk-foreground">
                {recheckError}
              </p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2 self-start sm:self-auto">
          {analysis.verdict && (
            <RiskScoreBar score={analysis.verdict.risk_score} />
          )}

          {canRecheck && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRecheck}
              disabled={isRechecking}
            >
              <RotateCw
                className={cn(
                  "h-3.5 w-3.5",
                  isRechecking && "animate-spin",
                )}
              />
              {isRechecking ? "Re-checking…" : "Re-check"}
            </Button>
          )}

          {analysis.verdict && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={() => setExpanded((prev) => !prev)}
              aria-expanded={expanded}
              aria-label={expanded ? "Hide details" : "View details"}
            >
              <ChevronDown
                className={cn(
                  "h-4 w-4 transition-transform",
                  expanded && "rotate-180",
                )}
              />
            </Button>
          )}
        </div>
      </div>

      {expanded && analysis.verdict && (
        <div className="mt-4 flex flex-col gap-3">
          <Separator />

          <p className="text-sm leading-relaxed text-muted-foreground">
            {analysis.verdict.reasoning}
          </p>

          <RedFlagList flags={analysis.verdict.red_flags} />
        </div>
      )}
    </div>
  );
}