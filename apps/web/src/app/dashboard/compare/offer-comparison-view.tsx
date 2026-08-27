"use client";

import type { AnalysisListResponse, OfferComparison } from "@offerleaks/shared-types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { LoadingRows } from "@/components/states/loading-rows";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

async function fetchCompletedOffers(): Promise<AnalysisListResponse> {
  const params = new URLSearchParams({ status: "complete", limit: "50", offset: "0" });
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

async function fetchComparison(idA: string, idB: string): Promise<OfferComparison> {
  const params = new URLSearchParams({ analysis_id_a: idA, analysis_id_b: idB });
  const response = await fetch(`/api/comparison?${params.toString()}`, { cache: "no-store" });
  const body = (await response
    .json()
    .catch(() => null)) as OfferComparison | { detail?: string } | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : undefined;
    throw new Error(detail ?? `Request failed: ${response.status}`);
  }
  return body as OfferComparison;
}

export function OfferComparisonView() {
  const [idA, setIdA] = useState<string>("");
  const [idB, setIdB] = useState<string>("");
  const [comparedIds, setComparedIds] = useState<{ a: string; b: string } | null>(null);

  const offersQuery = useQuery({
    queryKey: ["offers-for-comparison"],
    queryFn: fetchCompletedOffers,
  });

  const comparisonQuery = useQuery({
    queryKey: ["comparison", comparedIds?.a, comparedIds?.b],
    queryFn: () => fetchComparison(comparedIds!.a, comparedIds!.b),
    enabled: comparedIds !== null,
  });

  if (offersQuery.isPending) {
    return <LoadingRows />;
  }

  if (offersQuery.isError || !offersQuery.data) {
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertDescription>Couldn&apos;t load your scanned offers.</AlertDescription>
      </Alert>
    );
  }

  const offers = offersQuery.data.items;

  if (offers.length < 2) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          You need at least two completed scans to compare them. Scan another offer letter first.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="flex flex-col gap-4 p-6 sm:flex-row sm:items-end">
          <OfferSelect
            label="First offer"
            value={idA}
            onChange={setIdA}
            offers={offers}
            excludeId={idB}
          />
          <OfferSelect
            label="Second offer"
            value={idB}
            onChange={setIdB}
            offers={offers}
            excludeId={idA}
          />
          <Button
            size="sm"
            disabled={!idA || !idB || idA === idB}
            onClick={() => setComparedIds({ a: idA, b: idB })}
          >
            Compare
          </Button>
        </CardContent>
      </Card>

      {comparisonQuery.isPending && comparedIds && <LoadingRows />}

      {comparisonQuery.isError && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{comparisonQuery.error.message}</AlertDescription>
        </Alert>
      )}

      {comparisonQuery.data && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ComparisonColumn item={comparisonQuery.data.left} />
          <ComparisonColumn item={comparisonQuery.data.right} />
        </div>
      )}
    </div>
  );
}

function OfferSelect({
  label,
  value,
  onChange,
  offers,
  excludeId,
}: {
  label: string;
  value: string;
  onChange: (id: string) => void;
  offers: AnalysisListResponse["items"];
  excludeId: string;
}) {
  return (
    <label className="flex flex-1 flex-col gap-1.5 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      <select
        className="h-10 rounded-lg border border-input bg-card px-3 text-sm text-foreground shadow-subtle"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Choose an offer…</option>
        {offers
          .filter((offer) => offer.id !== excludeId)
          .map((offer) => (
            <option key={offer.id} value={offer.id}>
              {offer.file_name}
              {offer.verdict ? ` (risk ${offer.verdict.risk_score})` : ""}
            </option>
          ))}
      </select>
    </label>
  );
}

function ComparisonColumn({ item }: { item: OfferComparison["left"] }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-6">
        <h3 className="text-sm font-semibold text-foreground">{item.file_name}</h3>

        <Row
          label="Company"
          value={item.company_name ?? item.company_domain ?? "Not identified"}
        />
        <Row
          label="Verification"
          value={
            item.company_verification_status ? (
              <Badge variant="outline">{item.company_verification_status}</Badge>
            ) : (
              "—"
            )
          }
        />
        <Row
          label="Risk score"
          value={item.risk_score === null ? "—" : `${item.risk_score} / 100`}
        />
        <Row
          label="Confidence"
          value={item.confidence === null ? "—" : `${Math.round(item.confidence * 100)}%`}
        />
        <Row
          label="Red flags found"
          value={item.red_flag_count === null ? "—" : String(item.red_flag_count)}
        />
        <Row
          label="Matched scam patterns"
          value={item.matched_pattern_count === null ? "—" : String(item.matched_pattern_count)}
        />

        {item.recommended_actions.length > 0 && (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Recommended actions</span>
            <ul className="list-disc pl-4 text-xs text-foreground">
              {item.recommended_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}
