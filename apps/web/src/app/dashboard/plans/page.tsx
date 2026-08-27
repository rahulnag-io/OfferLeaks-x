import { redirect } from "next/navigation";
import type { Entitlements, Plan } from "@offerleaks/shared-types";

import { auth } from "@/auth";
import { PlanCard } from "@/components/billing/plan-card";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/states/error-state";
import { getEntitlementsUpstream, listPlansUpstream } from "@/lib/api";

export default async function PlansPage() {
  const session = await auth();
  if (!session?.user || !session.accessToken) {
    redirect("/login");
  }

  const accessToken = session.accessToken;

  const [plansResult, entitlementsResult] = await Promise.allSettled([
    listPlansUpstream().then((r) => (r.ok ? (r.json() as Promise<Plan[]>) : null)),
    getEntitlementsUpstream(accessToken).then((r) =>
      r.ok ? (r.json() as Promise<Entitlements>) : null,
    ),
  ]);

  const plans: Plan[] | null = plansResult.status === "fulfilled" ? plansResult.value : null;
  const entitlements: Entitlements | null =
    entitlementsResult.status === "fulfilled" ? entitlementsResult.value : null;

  if (!plans || plans.length === 0) {
    return (
      <div className="flex flex-col gap-8">
        <PageHeader title="Plans" description="Choose the plan that fits how often you scan offer letters." />
        <ErrorState message="We couldn't load plan details right now. Please try again shortly." />
      </div>
    );
  }

  const currentPlanKey = entitlements?.plan.key ?? "free";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Plans"
        description="Choose the plan that fits how often you scan offer letters. You can cancel anytime -- your Pro access continues through the end of your current billing period."
      />

      {entitlements?.cancel_at_period_end && entitlements.current_period_end && (
        <div className="rounded-lg border border-caution-bg bg-caution-bg px-4 py-3 text-sm text-caution-foreground">
          Your subscription is set to cancel on{" "}
          {new Date(entitlements.current_period_end).toLocaleDateString()}. You&apos;ll keep Pro
          access until then.
        </div>
      )}

      <div className="grid gap-6 sm:grid-cols-2 lg:max-w-3xl">
        {plans.map((plan) => (
          <PlanCard
            key={plan.key}
            plan={plan}
            isCurrentPlan={plan.key === currentPlanKey}
            highlighted={plan.key === "pro"}
          />
        ))}
      </div>
    </div>
  );
}
