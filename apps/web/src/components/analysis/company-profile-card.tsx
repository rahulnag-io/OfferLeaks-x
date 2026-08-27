import Link from "next/link";
import { Building2, CheckCircle2, HelpCircle, Lock, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { CompanyProfile, CompanyVerificationStatus } from "@/types/company";

/**
 * M7's company profile card: the fundamental Found/Not Found/unable-to-
 * verify result is always shown (never paywalled -- roadmap §12); the
 * advanced signals (domain age, website reachability, email-domain
 * match) only render when the backend actually included them, which it
 * only does for a Pro user (`_build_company_response` in the API). This
 * component never re-derives or guesses that gate itself -- an absent
 * `advanced` object always means "show the upsell," regardless of why.
 */
const STATUS_COPY: Record<
  CompanyVerificationStatus,
  { label: string; hint: string; icon: typeof CheckCircle2; variant: "safe" | "risk" | "caution" }
> = {
  found: {
    label: "Company verified",
    hint: "We found a registered domain and/or an active website for this company.",
    icon: CheckCircle2,
    variant: "safe",
  },
  not_found: {
    label: "Company not found",
    hint: "We couldn't find a registration record for this company's domain.",
    icon: XCircle,
    variant: "risk",
  },
  insufficient_evidence: {
    label: "Unable to verify",
    hint: "We don't have enough evidence to confirm or rule out this company yet.",
    icon: HelpCircle,
    variant: "caution",
  },
};

export function CompanyProfileCard({ company }: { company: CompanyProfile }) {
  const status = STATUS_COPY[company.verification_status];
  const StatusIcon = status.icon;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
          <h3 className="text-sm font-semibold text-foreground">
            {company.company_name ?? company.domain ?? "Unknown company"}
          </h3>
        </div>
        <Badge variant={status.variant} className="shrink-0">
          <StatusIcon className="h-3.5 w-3.5" strokeWidth={2} />
          {status.label}
        </Badge>
      </div>

      <p className="text-xs text-muted-foreground">{status.hint}</p>

      {company.advanced ? (
        <dl className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
          <SignalRow
            label="Domain age"
            value={
              company.advanced.domain_age_days === null
                ? "Unknown"
                : `${Math.floor(company.advanced.domain_age_days / 365)} yr`
            }
          />
          <SignalRow
            label="Website reachable"
            value={
              company.advanced.website_reachable === null
                ? "Unknown"
                : company.advanced.website_reachable
                  ? "Yes"
                  : "No"
            }
          />
          <SignalRow
            label="Sender domain match"
            value={
              company.advanced.email_domain_match === null
                ? "Unknown"
                : company.advanced.email_domain_match
                  ? "Matches"
                  : "Mismatch"
            }
          />
        </dl>
      ) : (
        <Link
          href="/dashboard/plans"
          className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-xs font-medium text-primary hover:underline"
        >
          <Lock className="h-3.5 w-3.5" strokeWidth={2} />
          Upgrade to Pro to see domain age, website reachability, and sender-domain match
        </Link>
      )}

      <p className="text-xs text-muted-foreground">
        Last checked {new Date(company.last_checked_at).toLocaleString()}
      </p>
    </div>
  );
}

function SignalRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg bg-muted/50 px-2.5 py-1.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium text-foreground">{value}</dd>
    </div>
  );
}
