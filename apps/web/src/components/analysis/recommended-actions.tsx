import { ShieldAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * M6: renders `Verdict.recommended_actions` -- a short, rule-based
 * (never AI-generated, see apps/api's `services/rules_engine.py`) list
 * of next steps. Kept visually distinct from `AnalysisSummary`'s
 * "What we found" reasoning text: this is prescriptive ("do this next"),
 * that's descriptive ("here's what we noticed") -- conflating the two
 * would make it look like the model itself is telling the user what to
 * do, which it isn't.
 */
export function RecommendedActions({ actions }: { actions: string[] }) {
  if (actions.length === 0) {
    return null;
  }

  return (
    <Alert variant="default">
      <ShieldAlert />
      <div>
        <AlertTitle>What to do next</AlertTitle>
        <AlertDescription>
          <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-4">
            {actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </AlertDescription>
      </div>
    </Alert>
  );
}
