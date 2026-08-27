import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AnalysisHistory } from "@/app/dashboard/history/analysis-history";
import { PageHeader } from "@/components/layout/page-header";

export default async function HistoryPage() {
  const session = await auth();
  if (!session?.user) {
    redirect("/login");
  }

  return (
    <div>
      <PageHeader
        title="History"
        description="Every offer letter you've checked, what each check cost, and its verdict."
      />

      {/* Client Component: never receives the backend access token -- it
          talks to this app's own /api/analyses route(s), which attach the
          token server-side (see app/api/analyses/route.ts). */}
      <AnalysisHistory />
    </div>
  );
}
