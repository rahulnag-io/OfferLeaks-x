import type { PersonalAnalytics } from "@offerleaks/shared-types";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState } from "@/components/states/error-state";
import { Card, CardContent } from "@/components/ui/card";
import { getAnalyticsUpstream } from "@/lib/api";

/**
 * Personal scam analytics (M8). Free for every plan -- no entitlement
 * check on this page, matching the backend (`GET /analytics/me` has no
 * gating at all).
 */
export default async function AnalyticsPage() {
  const session = await auth();
  if (!session?.user || !session.accessToken) {
    redirect("/login");
  }

  const upstream = await getAnalyticsUpstream(session.accessToken);
  const stats: PersonalAnalytics | null = upstream.ok
    ? ((await upstream.json()) as PersonalAnalytics)
    : null;

  if (!stats) {
    return (
      <div className="flex flex-col gap-8">
        <PageHeader
          title="Your scam analytics"
          description="A summary of everything you've scanned so far."
        />
        <ErrorState message="We couldn't load your analytics right now. Please try again shortly." />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Your scam analytics"
        description="A summary of everything you've scanned so far, computed from your own history."
      />

      {stats.total_analyses === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            You haven&apos;t scanned any offer letters yet. Once you do, your personal statistics
            will show up here.
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard label="Offers scanned" value={String(stats.total_analyses)} />
            <StatCard
              label="Average risk score"
              value={
                stats.average_risk_score === null
                  ? "—"
                  : `${Math.round(stats.average_risk_score)} / 100`
              }
            />
            <StatCard label="Companies checked" value={String(stats.distinct_companies_checked)} />
            <StatCard label="Reports you've filed" value={String(stats.reports_submitted)} />
          </div>

          <Card>
            <CardContent className="flex flex-col gap-4 p-6">
              <h3 className="text-sm font-semibold text-foreground">Risk breakdown</h3>
              <div className="flex flex-col gap-3">
                <RiskBar
                  label="High risk"
                  count={stats.high_risk_count}
                  total={stats.completed_analyses}
                  colorClassName="bg-risk-bg"
                />
                <RiskBar
                  label="Medium risk"
                  count={stats.medium_risk_count}
                  total={stats.completed_analyses}
                  colorClassName="bg-caution-bg"
                />
                <RiskBar
                  label="Low risk"
                  count={stats.low_risk_count}
                  total={stats.completed_analyses}
                  colorClassName="bg-safe-bg"
                />
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4">
        <span className="text-2xl font-semibold tabular-nums text-foreground">{value}</span>
        <span className="text-xs text-muted-foreground">{label}</span>
      </CardContent>
    </Card>
  );
}

function RiskBar({
  label,
  count,
  total,
  colorClassName,
}: {
  label: string;
  count: number;
  total: number;
  colorClassName: string;
}) {
  const percent = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>
          {count} ({percent}%)
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div className={`h-full rounded-full ${colorClassName}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
