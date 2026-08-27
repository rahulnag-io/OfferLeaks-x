import type { Plan } from "@offerleaks/shared-types";
import { Check } from "lucide-react";

import { SubscribeButton } from "@/components/billing/subscribe-button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function formatPrice(amountMinor: number, currency: string): string {
  if (amountMinor === 0) return "Free";
  const major = amountMinor / 100;
  // Intl.NumberFormat handles currency symbol placement correctly per
  // currency (₹ before the amount for INR) without us hardcoding one.
  return `${new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(major)}/mo`;
}

export function PlanCard({
  plan,
  isCurrentPlan,
  highlighted,
}: {
  plan: Plan;
  isCurrentPlan: boolean;
  highlighted?: boolean;
}) {
  const isFreePlan = plan.key === "free";

  const features = [
    plan.monthly_analysis_limit === null
      ? "Unlimited offer letter scans"
      : `${plan.monthly_analysis_limit} offer letter scans / month`,
    plan.monthly_credit_grant > 0
      ? `${plan.monthly_credit_grant} credits every month`
      : "3 free credits to get started",
    "AI verdict with red flags and evidence highlighting",
    "Scam Pattern Library detection",
  ];

  return (
    <Card
      className={cn(
        "relative flex flex-col",
        highlighted && "border-primary shadow-md ring-1 ring-primary",
      )}
    >
      {isCurrentPlan && (
        <Badge variant="safe" className="absolute right-4 top-4">
          Current plan
        </Badge>
      )}

      <CardHeader>
        <CardTitle>{plan.name}</CardTitle>
        <p className="text-3xl font-semibold text-foreground">
          {formatPrice(plan.price_amount_minor, plan.price_currency)}
        </p>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-6">
        <ul className="flex flex-1 flex-col gap-2.5 text-sm text-muted-foreground">
          {features.map((feature) => (
            <li key={feature} className="flex items-start gap-2">
              <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" strokeWidth={2} />
              <span>{feature}</span>
            </li>
          ))}
        </ul>

        <SubscribeButton planKey={plan.key} isCurrentPlan={isCurrentPlan} isFreePlan={isFreePlan} />
      </CardContent>
    </Card>
  );
}
