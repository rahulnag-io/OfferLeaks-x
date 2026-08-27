import type { Entitlements } from "@offerleaks/shared-types";
import Link from "next/link";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { OfferComparisonView } from "@/app/dashboard/compare/offer-comparison-view";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getEntitlementsUpstream } from "@/lib/api";

/**
 * Two-offer comparison (M8, Pro-gated). The backend is the
 * authoritative gate (`GET /comparison` returns 402 for a non-Pro
 * user) -- this server-side check is a UX courtesy so a Free user sees
 * an upsell instead of a raw 402, not the enforcement mechanism itself.
 */
export default async function ComparePage() {
  const session = await auth();
  if (!session?.user || !session.accessToken) {
    redirect("/login");
  }

  const upstream = await getEntitlementsUpstream(session.accessToken);
  const entitlements: Entitlements | null = upstream.ok
    ? ((await upstream.json()) as Entitlements)
    : null;
  const isPro = entitlements?.plan.key === "pro";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Compare offers"
        description="See two of your scanned offers side by side."
      />

      {isPro ? (
        <OfferComparisonView />
      ) : (
        <Card>
          <CardContent className="flex flex-col items-start gap-3 p-6">
            <p className="text-sm text-foreground">
              Comparing offers side by side is a Pro feature.
            </p>
            <Button asChild size="sm">
              <Link href="/dashboard/plans">Upgrade to Pro</Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
