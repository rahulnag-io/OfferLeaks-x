import { redirect } from "next/navigation";
import Link from "next/link";
import type { Analysis, AnalysisListResponse, CreditBalance, Entitlements, User } from "@offerleaks/shared-types";
import { ArrowRight, FileSearch, History as HistoryIcon, ShieldCheck } from "lucide-react";

import { auth } from "@/auth";
import { AnalysisHistoryItem } from "@/components/analysis/analysis-history-item";
import { CreditBalanceBadge } from "@/components/analysis/credit-balance";
import { PlanUsageBadge } from "@/components/billing/plan-usage-badge";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getCreditsUpstream, getCurrentUser, getEntitlementsUpstream, listAnalysesUpstream } from "@/lib/api";

const RECENT_LIMIT = 3;

export default async function DashboardPage() {
  const session = await auth();
  if (!session?.user || !session.accessToken) {
    redirect("/login");
  }

  const accessToken = session.accessToken;

  // Each panel below is independent and only ever reads from endpoints
  // that already exist (`/users/me`, `/credits/me`, `/analyses`,
  // `/billing/me`) -- Promise.allSettled so one failing panel never
  // blanks the others.
  const [userResult, creditsResult, recentResult, entitlementsResult] = await Promise.allSettled([
    getCurrentUser(accessToken),
    getCreditsUpstream(accessToken).then((r) =>
      r.ok ? (r.json() as Promise<CreditBalance>) : null,
    ),
    listAnalysesUpstream(accessToken, `?limit=${RECENT_LIMIT}&offset=0`).then((r) =>
      r.ok ? (r.json() as Promise<AnalysisListResponse>) : null,
    ),
    getEntitlementsUpstream(accessToken).then((r) =>
      r.ok ? (r.json() as Promise<Entitlements>) : null,
    ),
  ]);

  const user: User | null =
    userResult.status === "fulfilled" ? userResult.value : null;

  const credits: CreditBalance | null =
    creditsResult.status === "fulfilled" ? creditsResult.value : null;

  const recent: AnalysisListResponse | null =
    recentResult.status === "fulfilled" ? recentResult.value : null;

  const entitlements: Entitlements | null =
    entitlementsResult.status === "fulfilled" ? entitlementsResult.value : null;

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={
          user?.full_name
            ? `Welcome back, ${user.full_name.split(" ")[0]}`
            : "Welcome back"
        }
        description="Check a new offer letter, or pick up where you left off."
        actions={
          <Button asChild size="lg">
            <Link href="/dashboard/upload">
              <FileSearch className="h-4 w-4" />
              Scan a new letter
            </Link>
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {credits && (
          <div className="lg:col-span-1">
            <CreditBalanceBadge
              balance={credits.balance}
              costPerAnalysis={credits.cost_per_analysis}
            />
          </div>
        )}

        {entitlements && (
          <div className="lg:col-span-1">
            <PlanUsageBadge entitlements={entitlements} />
          </div>
        )}

        <Card className="sm:col-span-2 lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Your account
            </CardTitle>
            <ShieldCheck className="h-4 w-4 text-primary-700" />
          </CardHeader>

          <CardContent className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Email</dt>
              <dd className="truncate font-medium text-foreground">
                {user?.email ?? "—"}
              </dd>
            </div>

            <div>
              <dt className="text-xs text-muted-foreground">Name</dt>
              <dd className="truncate font-medium text-foreground">
                {user?.full_name ?? "—"}
              </dd>
            </div>

            <div>
              <dt className="text-xs text-muted-foreground">Role</dt>
              <dd className="font-medium capitalize text-foreground">
                {user?.role ?? "—"}
              </dd>
            </div>

            <div>
              <dt className="text-xs text-muted-foreground">Email verified</dt>
              <dd className="font-medium text-foreground">
                {user ? (user.email_verified ? "Yes" : "No") : "—"}
              </dd>
            </div>
          </CardContent>
        </Card>
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold text-foreground">
            Recent activity
          </h2>

          <Link
            href="/dashboard/history"
            className="flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            View all history
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>

        {recent && recent.items.length > 0 ? (
          <div className="flex flex-col gap-3">
            {recent.items.map((item: Analysis) => (
              <AnalysisHistoryItem
                key={item.id}
                analysis={item}
                readOnly
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={HistoryIcon}
            title="No analyses yet"
            description="Once you scan an offer letter, it'll show up here with its verdict and cost."
            action={
              <Button asChild variant="outline" size="sm">
                <Link href="/dashboard/upload">
                  Scan your first letter
                </Link>
              </Button>
            }
          />
        )}
      </div>
    </div>
  );
}