"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AnalysisStatus, CreditBalance } from "@offerleaks/shared-types";
import { useEffect, useState } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";

import { AnalysisSummary } from "@/components/analysis/analysis-summary";
import { CompanyProfileCard } from "@/components/analysis/company-profile-card";
import { CreditBalanceBadge } from "@/components/analysis/credit-balance";
import { ProcessingState } from "@/components/analysis/processing-state";
import { ReportCompanyDialog } from "@/components/analysis/report-company-dialog";
import { UploadDropzone } from "@/components/analysis/upload-dropzone";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { IN_PROGRESS_STATUSES } from "@/lib/risk";
import type { AnalysisWithCompany, CompanyProfile } from "@/types/company";

// Statuses the backend is still working on -- keep polling. Anything
// else (complete/failed/needs_manual_review) is terminal.
// Terminal statuses the worker may have just refunded a credit for (see
// `_refund_credits` in `offerleaks.worker`) -- the credit badge needs a
// refetch right when the poller lands on one of these, not just at
// upload time, since the refund (if any) happens later, in the
// background job, not synchronously with the request that created it.
const REFUND_ELIGIBLE_STATUSES: readonly AnalysisStatus[] = ["failed", "needs_manual_review"];
const POLL_INTERVAL_MS = 2000;
const CREDITS_QUERY_KEY = ["credits"] as const;

async function fetchAnalysis(id: string): Promise<AnalysisWithCompany> {
  const response = await fetch(`/api/analyses/${id}`, { cache: "no-store" });
  const body = (await response.json().catch(() => null)) as AnalysisWithCompany | { detail?: string } | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : undefined;
    throw new Error(detail ?? `Request failed: ${response.status}`);
  }
  return body as AnalysisWithCompany;
}

async function fetchCredits(): Promise<CreditBalance> {
  const response = await fetch("/api/credits", { cache: "no-store" });
  const body = (await response
    .json()
    .catch(() => null)) as CreditBalance | { detail?: string } | null;
  if (!response.ok) {
    const detail = body && "detail" in body ? body.detail : undefined;
    throw new Error(detail ?? `Request failed: ${response.status}`);
  }
  return body as CreditBalance;
}

export function AnalysisUploader() {
  const [file, setFile] = useState<File | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const queryClient = useQueryClient();

  const creditsQuery = useQuery({
    queryKey: CREDITS_QUERY_KEY,
    queryFn: fetchCredits,
  });

  const analysisQuery = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => fetchAnalysis(analysisId as string),
    enabled: analysisId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && IN_PROGRESS_STATUSES.includes(status) ? POLL_INTERVAL_MS : false;
    },
  });

  // The poller above only tells us the document's status -- it doesn't
  // push balance changes. A refund (see `_refund_credits` in the worker)
  // can land any time after the job starts processing, so the credit
  // badge needs its own refetch the moment we observe a status that may
  // have just triggered one, rather than only right after upload.
  const analysisStatus = analysisQuery.data?.status;
  useEffect(() => {
    if (analysisStatus && REFUND_ELIGIBLE_STATUSES.includes(analysisStatus)) {
      void queryClient.invalidateQueries({ queryKey: CREDITS_QUERY_KEY });
    }
  }, [analysisStatus, queryClient]);

  // The displayed balance is only ever a hint for the UI -- it is never
  // what actually authorizes an analysis (the backend re-checks on every
  // submit and can still return 402 even when this looks sufficient, e.g.
  // if it was just spent in another tab). Disabling the button on a
  // visibly-zero balance is a courtesy, not the enforcement mechanism.
  const hasVisibleCredits =
    creditsQuery.data === undefined || creditsQuery.data.balance >= creditsQuery.data.cost_per_analysis;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setUploadError(null);

    if (!file) {
      setUploadError("Choose a file first.");
      return;
    }

    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.set("file", file);

      const response = await fetch("/api/analyses", { method: "POST", body: formData });
      const body = (await response.json().catch(() => null)) as
        | AnalysisWithCompany
        | { detail?: string }
        | null;

      if (!response.ok) {
        const detail = body && "detail" in body ? body.detail : undefined;
        if (response.status === 402) {
          // The balance shown before submitting may have been stale (see
          // `hasVisibleCredits` above) -- this is the backend's
          // authoritative rejection, always trust it over what was shown.
          setUploadError(detail ?? "You're out of credits.");
        } else {
          setUploadError(detail ?? `Upload failed: ${response.status}`);
        }
        return;
      }

      setAnalysisId((body as AnalysisWithCompany).id);
      // The submit that just succeeded consumed a credit -- refetch
      // rather than assume, so the displayed balance never drifts from
      // what the backend actually holds.
      void queryClient.invalidateQueries({ queryKey: CREDITS_QUERY_KEY });
    } catch {
      setUploadError("Could not reach the server. Please try again.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="mt-8 flex flex-col gap-6">
      {creditsQuery.data && (
        <CreditBalanceBadge balance={creditsQuery.data.balance} costPerAnalysis={creditsQuery.data.cost_per_analysis} />
      )}

      <Card>
        <CardContent className="flex flex-col gap-4 p-6">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <UploadDropzone file={file} onFileChange={setFile} disabled={isUploading} />

            {uploadError && (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>{uploadError}</AlertDescription>
              </Alert>
            )}

            <Button type="submit" size="lg" disabled={isUploading || !hasVisibleCredits || !file}>
              {isUploading ? "Uploading…" : hasVisibleCredits ? "Analyze this letter" : "Out of credits"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {analysisId && <AnalysisResult query={analysisQuery} />}
    </div>
  );
}

function AnalysisResult({ query }: { query: ReturnType<typeof useQuery<AnalysisWithCompany, Error>> }) {
  if (query.isPending) {
    return (
      <Card className="animate-fade-in">
        <CardContent className="p-6">
          <ProcessingState status="pending" />
        </CardContent>
      </Card>
    );
  }

  if (query.isError) {
    return (
      <Alert variant="destructive" className="animate-fade-in">
        <AlertTriangle />
        <AlertTitle>Couldn&apos;t load this analysis</AlertTitle>
        <AlertDescription>{query.error.message}</AlertDescription>
      </Alert>
    );
  }

  const analysis = query.data;

  if (analysis.status === "pending" || analysis.status === "processing") {
    return (
      <Card className="animate-fade-in">
        <CardContent className="p-6">
          <ProcessingState status={analysis.status} />
        </CardContent>
      </Card>
    );
  }

  if (analysis.status === "failed") {
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="destructive" className="animate-fade-in">
          <AlertTriangle />
          <AlertTitle>We couldn&apos;t analyze this document</AlertTitle>
          <AlertDescription>
            <p>{analysis.error_message ?? "Something went wrong analyzing this document."}</p>
            {analysis.credit_refunded && (
              <p className="mt-1 font-medium">Your credit for this analysis has been refunded.</p>
            )}
          </AlertDescription>
        </Alert>
        {/* Company resolution runs *after* OCR succeeds, and a `failed`
            status can also mean OCR/storage failed before resolution
            ever got a chance to run -- so `company` being absent here is
            genuinely ambiguous (never attempted vs. attempted and found
            nothing), unlike the other branches below. Show the card if
            we do have one; stay silent rather than show a possibly-wrong
            "couldn't identify" message otherwise. */}
        {analysis.company && (
          <CompanySection company={analysis.company} analysisId={analysis.id} />
        )}
      </div>
    );
  }

  if (analysis.status === "needs_manual_review") {
    return (
      <div className="flex flex-col gap-4">
        <Alert variant="caution" className="animate-fade-in">
          <ShieldAlert />
          <AlertTitle>Queued for manual review</AlertTitle>
          <AlertDescription>
            <p>
              {analysis.error_message ??
                "Automatic analysis is temporarily unavailable; this has been queued for manual review."}
            </p>
            {analysis.credit_refunded && (
              <p className="mt-1 font-medium">Your credit for this analysis has been refunded.</p>
            )}
          </AlertDescription>
        </Alert>
        <CompanySection company={analysis.company} analysisId={analysis.id} />
      </div>
    );
  }

  const verdict = analysis.verdict;
  if (!verdict) {
    return (
      <Alert variant="destructive" className="animate-fade-in">
        <AlertTriangle />
        <AlertDescription>Analysis complete, but no verdict was returned.</AlertDescription>
      </Alert>
    );
  }

  return (
    <Card className="animate-fade-in">
      <CardContent className="flex flex-col gap-6 p-6">
        <AnalysisSummary verdict={verdict} />
        <CompanySection company={analysis.company} analysisId={analysis.id} />
      </CardContent>
    </Card>
  );
}

/**
 * Company resolution (`worker._attach_company_profile`) runs
 * unconditionally, ahead of the AI call, so it can succeed even when the
 * AI verdict later fails or needs manual review -- this renders
 * wherever `analysis.company` might be present, not only alongside a
 * completed verdict.
 *
 * `analysis.company` being `null` is ambiguous on its own: it's the same
 * value whether resolution ran and genuinely found nothing extractable,
 * or hasn't been attempted for some other reason. Rather than showing
 * nothing either way (indistinguishable from the feature not existing),
 * this renders an explicit "couldn't identify a company" note -- an
 * honest signal, in the spirit of the same "insufficient evidence, never
 * silence" principle the backend applies once a company *is* resolved.
 *
 * `analysisId` is passed through so "Report this company" (M8) can
 * submit a `target_type: "offer"` report against this specific
 * analysis -- see `ReportCompanyDialog` for why that's the report
 * shape used here, rather than a `company_id`.
 */
function CompanySection({
  company,
  analysisId,
}: {
  company: CompanyProfile | null | undefined;
  analysisId: string;
}) {
  const [isReporting, setIsReporting] = useState(false);

  if (company) {
    return (
      <div className="flex flex-col gap-2">
        <CompanyProfileCard company={company} />
        <div>
          <Button variant="outline" size="sm" onClick={() => setIsReporting(true)}>
            Report this company
          </Button>
        </div>
        {isReporting && (
          <ReportCompanyDialog
            analysisId={analysisId}
            companyLabel={company.company_name ?? company.domain ?? "this company"}
            onClose={() => setIsReporting(false)}
          />
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
      We couldn&apos;t identify a company for this document, so no company profile is available.
    </div>
  );
}
