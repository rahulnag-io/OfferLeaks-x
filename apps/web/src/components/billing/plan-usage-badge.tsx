import type { Entitlements } from "@offerleaks/shared-types";
import Link from "next/link";
import { Sparkles } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

/**
 * M6's plan/usage indicator for the dashboard -- companion to
 * `CreditBalanceBadge`: credits are "how much automated-analysis budget
 * is left," this is "how much of this month's plan allowance is used."
 * The two are independent gates (see apps/api's `EntitlementService`
 * docstring), so they're shown as two separate cards rather than merged
 * into one, to avoid implying they're the same number.
 */
export function PlanUsageBadge({ entitlements }: { entitlements: Entitlements }) {
  const { plan, monthly_analyses_used: used, monthly_analysis_limit: limit } = entitlements;
  const unlimited = limit === null;
  const usagePercent = unlimited ? 0 : Math.min(100, Math.round((used / Math.max(limit, 1)) * 100));
  const nearLimit = !unlimited && used >= limit;

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border px-4 py-3 text-sm",
        nearLimit ? "border-caution-bg bg-caution-bg text-caution-foreground" : "border-border bg-card text-foreground",
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <span className="flex items-center gap-2 font-medium">
          <Sparkles className="h-4 w-4" strokeWidth={2} />
          {plan.name} plan
        </span>
        {plan.key === "free" && (
          <Link href="/dashboard/plans" className="text-xs font-medium text-primary hover:underline">
            Upgrade
          </Link>
        )}
      </div>

      {unlimited ? (
        <span className="text-xs text-muted-foreground">Unlimited scans this month</span>
      ) : (
        <>
          <Progress value={usagePercent} />
          <span className="text-xs text-muted-foreground">
            {used} of {limit} scans used this month
          </span>
        </>
      )}
    </div>
  );
}
