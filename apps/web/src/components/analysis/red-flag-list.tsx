import type { RedFlag } from "@offerleaks/shared-types";
import { AlertOctagon, Quote } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { SEVERITY_BADGE_VARIANT, SEVERITY_LABEL } from "@/lib/risk";

export function RedFlagList({ flags }: { flags: RedFlag[] }) {
  if (flags.length === 0) {
    return (
      <p className="rounded-lg bg-safe-bg px-3 py-2.5 text-sm text-safe-foreground">
        No red flags were found in this document.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-2.5">
      {flags.map((flag) => (
        <li key={flag.title} className="flex items-start gap-3 rounded-lg border border-border bg-card p-3.5">
          <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={2} />
          <div className="flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-foreground">{flag.title}</span>
              <Badge variant={SEVERITY_BADGE_VARIANT[flag.severity]}>{SEVERITY_LABEL[flag.severity]}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{flag.description}</p>
            {/* M6: the exact text from the document backing this flag,
                when the model (or the rules engine, for a pattern match)
                could point to one. Rendered as a quote block, distinct
                from `description`'s prose, so it's visually clear this
                came from the letter itself, not our own analysis. */}
            {flag.evidence_quote && (
              <blockquote className="mt-2 flex items-start gap-1.5 rounded-md bg-muted/50 px-2.5 py-2 text-xs italic text-muted-foreground">
                <Quote className="mt-0.5 h-3 w-3 shrink-0" strokeWidth={2} />
                <span>&ldquo;{flag.evidence_quote}&rdquo;</span>
              </blockquote>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
