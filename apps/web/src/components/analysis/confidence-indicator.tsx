import { Gauge } from "lucide-react";

export function ConfidenceIndicator({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground" title="How confident the analysis is in this verdict">
      <Gauge className="h-3.5 w-3.5" strokeWidth={2} />
      <span>
        Confidence <span className="font-mono font-medium text-foreground">{pct}%</span>
      </span>
    </div>
  );
}
