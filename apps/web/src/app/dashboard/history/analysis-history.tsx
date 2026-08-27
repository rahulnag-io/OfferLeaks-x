"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AnalysisListResponse, AnalysisStatus } from "@offerleaks/shared-types";
import { useState } from "react";
import { History as HistoryIcon, Search } from "lucide-react";

import { AnalysisHistoryItem } from "@/components/analysis/analysis-history-item";
import { EmptyState } from "@/components/states/empty-state";
import { ErrorState } from "@/components/states/error-state";
import { LoadingRows } from "@/components/states/loading-rows";
import { Button } from "@/components/ui/button";
import { STATUS_LABEL } from "@/lib/risk";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;
const CREDITS_QUERY_KEY = ["credits"] as const;

const STATUS_FILTERS: { label: string; value: AnalysisStatus | "all" }[] = [
  { label: "All", value: "all" },
  { label: STATUS_LABEL.complete, value: "complete" },
  { label: STATUS_LABEL.pending, value: "pending" },
  { label: STATUS_LABEL.processing, value: "processing" },
  { label: STATUS_LABEL.failed, value: "failed" },
  { label: STATUS_LABEL.needs_manual_review, value: "needs_manual_review" },
];

async function fetchAnalyses(
  statusFilter: AnalysisStatus | "all",
  offset: number,
): Promise<AnalysisListResponse> {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
  if (statusFilter !== "all") {
    params.set("status", statusFilter);
  }
  const response = await fetch(`/api/analyses?${params.toString()}`, { cache: "no-store" });
  const body = (await response
    .json()
    .catch(() => null)) as AnalysisListResponse | { detail?: string } | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : undefined;
    throw new Error(detail ?? `Request failed: ${response.status}`);
  }
  return body as AnalysisListResponse;
}

export function AnalysisHistory() {
  const [statusFilter, setStatusFilter] = useState<AnalysisStatus | "all">("all");
  const [offset, setOffset] = useState(0);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["analyses", statusFilter, offset],
    queryFn: () => fetchAnalyses(statusFilter, offset),
  });

  function handleFilterChange(next: AnalysisStatus | "all") {
    setStatusFilter(next);
    setOffset(0);
  }

  function invalidateAfterRecheck() {
    void queryClient.invalidateQueries({ queryKey: ["analyses"] });
    void queryClient.invalidateQueries({ queryKey: CREDITS_QUERY_KEY });
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => handleFilterChange(filter.value)}
            aria-pressed={statusFilter === filter.value}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              statusFilter === filter.value
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {query.isPending && <LoadingRows />}

      {query.isError && <ErrorState message={query.error.message} onRetry={() => query.refetch()} />}

      {query.data && query.data.total === 0 && (
        <EmptyState
          icon={statusFilter === "all" ? HistoryIcon : Search}
          title={statusFilter === "all" ? "No analyses yet" : "No analyses match this filter"}
          description={
            statusFilter === "all"
              ? "Once you check an offer letter, it'll show up here."
              : "Try a different status filter to see other analyses."
          }
          action={
            statusFilter !== "all" ? (
              <Button variant="outline" size="sm" onClick={() => handleFilterChange("all")}>
                Clear filter
              </Button>
            ) : undefined
          }
        />
      )}

      {query.data && query.data.items.length > 0 && (
        <div className="flex flex-col gap-3">
          {query.data.items.map((item) => (
            <AnalysisHistoryItem key={item.id} analysis={item} onRecheckSucceeded={invalidateAfterRecheck} />
          ))}
        </div>
      )}

      {query.data && query.data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between border-t border-border pt-4 text-sm text-muted-foreground">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </Button>
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, query.data.total)} of {query.data.total}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= query.data.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
