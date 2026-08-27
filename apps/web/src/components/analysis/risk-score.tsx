import { getRiskLevel, RISK_LEVEL_COPY, RISK_LEVEL_GAUGE_VAR } from "@/lib/risk";
import { cn } from "@/lib/utils";

/**
 * The verification ring -- OfferLeaks' signature visual device. Renders
 * the backend's own 0-100 risk_score as a radial gauge with the exact
 * number at its center; the surrounding label is a grouping, never a
 * replacement for the number.
 */
export function RiskScoreRing({ score, size = "lg" }: { score: number; size?: "lg" | "md" }) {
  const level = getRiskLevel(score);
  const dimension = size === "lg" ? 168 : 112;

  return (
    <div className="flex flex-col items-center gap-3">
      <div
        className="risk-gauge relative flex items-center justify-center rounded-full p-[10px]"
        style={
          {
            width: dimension,
            height: dimension,
            "--gauge-value": score,
            "--gauge-color": RISK_LEVEL_GAUGE_VAR[level],
          } as React.CSSProperties
        }
      >
        <div className="flex h-full w-full flex-col items-center justify-center rounded-full bg-card">
          <span className={cn("font-mono font-semibold leading-none text-foreground", size === "lg" ? "text-4xl" : "text-2xl")}>
            {Math.round(score)}
          </span>
          <span className="mt-1 text-[11px] uppercase tracking-wide text-muted-foreground">/ 100</span>
        </div>
      </div>
      <div className="text-center">
        <p className="text-sm font-semibold text-foreground">{RISK_LEVEL_COPY[level].label}</p>
        <p className="text-xs text-muted-foreground">{RISK_LEVEL_COPY[level].hint}</p>
      </div>
    </div>
  );
}

const RISK_LEVEL_BAR_CLASS: Record<ReturnType<typeof getRiskLevel>, string> = {
  low: "bg-safe",
  medium: "bg-caution",
  high: "bg-risk",
};

export function RiskScoreBar({ score }: { score: number }) {
  const level = getRiskLevel(score);
  return (
    <div className="flex min-w-[128px] items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-secondary">
        <div className={cn("h-full rounded-full", RISK_LEVEL_BAR_CLASS[level])} style={{ width: `${score}%` }} />
      </div>
      <span className="font-mono text-xs font-medium text-foreground">{Math.round(score)}/100</span>
    </div>
  );
}
