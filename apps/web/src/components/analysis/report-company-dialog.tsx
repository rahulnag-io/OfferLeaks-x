"use client";

import type { ReportCreateRequest, ReportReason } from "@offerleaks/shared-types";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, Flag } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/**
 * "Report this company" (M8 §12). Submitted as `target_type: "offer"`
 * against the current analysis, not `target_type: "company"` with a
 * `company_id` -- `CompanyProfileResponse` (M7) deliberately has no
 * `id` field (M7 §"there is no standalone `/companies` endpoint"), so
 * this is the smallest non-invasive way to reuse the existing
 * verdict/company context the roadmap asks for: `ReportService.
 * submit_report` already derives `company_id` from the analysis's own
 * resolved company for an OFFER-targeted report, so no backend
 * contract change is needed for the "report this company" flow to
 * work end to end.
 */
const REASON_OPTIONS: { value: ReportReason; label: string }[] = [
  { value: "upfront_payment_request", label: "Asked me to pay money upfront" },
  { value: "fake_or_unregistered_company", label: "Company appears fake or unregistered" },
  { value: "identity_or_document_theft", label: "Asked for sensitive personal documents" },
  { value: "unrealistic_salary_or_offer", label: "Salary or offer seemed unrealistic" },
  { value: "pressure_or_urgency_tactics", label: "Pressured me to respond immediately" },
  { value: "impersonation_of_real_company", label: "Impersonating a real, known company" },
  { value: "no_interview_or_unverifiable_process", label: "No real interview process" },
  { value: "suspicious_contact_channel", label: "Contacted me through a suspicious channel" },
  { value: "other", label: "Something else" },
];

const MIN_DESCRIPTION_LENGTH = 10;

export function ReportCompanyDialog({
  analysisId,
  companyLabel,
  onClose,
}: {
  analysisId: string;
  companyLabel: string;
  onClose: () => void;
}) {
  const [selectedReasons, setSelectedReasons] = useState<ReportReason[]>([]);
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  function toggleReason(reason: ReportReason) {
    setSelectedReasons((current) =>
      current.includes(reason) ? current.filter((r) => r !== reason) : [...current, reason],
    );
  }

  const canSubmit =
    selectedReasons.length > 0 && description.trim().length >= MIN_DESCRIPTION_LENGTH;

  async function handleSubmit() {
    if (!canSubmit) return;
    setError(null);
    setIsSubmitting(true);

    try {
      const payload: ReportCreateRequest = {
        target_type: "offer",
        analysis_id: analysisId,
        reasons: selectedReasons,
        description: description.trim(),
      };
      const response = await fetch("/api/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;

      if (!response.ok) {
        setError(body?.detail ?? `Could not submit report: ${response.status}`);
        return;
      }

      setSucceeded(true);
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-md flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        {succeeded ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <CheckCircle2 className="h-8 w-8 text-safe-foreground" strokeWidth={2} />
            <p className="text-sm font-semibold text-foreground">Report submitted</p>
            <p className="text-xs text-muted-foreground">
              Thanks -- this stays private and helps us track patterns across similar reports.
            </p>
            <Button size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Flag className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
              <h3 className="text-sm font-semibold text-foreground">Report {companyLabel}</h3>
            </div>
            <p className="text-xs text-muted-foreground">
              This report is private -- it&apos;s never shown publicly or to other users. It
              helps us track patterns and improve how we flag risky offers.
            </p>

            <div className="flex flex-col gap-2">
              <Label>What happened? (select all that apply)</Label>
              <div className="flex flex-col gap-1.5">
                {REASON_OPTIONS.map((option) => (
                  <label
                    key={option.value}
                    className="flex items-center gap-2 text-sm text-foreground"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      checked={selectedReasons.includes(option.value)}
                      onChange={() => toggleReason(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="report-description">Tell us more</Label>
              <Textarea
                id="report-description"
                placeholder="Describe what happened, in your own words."
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                disabled={isSubmitting}
              />
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTriangle />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={onClose} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleSubmit} disabled={!canSubmit || isSubmitting}>
                {isSubmitting ? "Submitting…" : "Submit report"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
