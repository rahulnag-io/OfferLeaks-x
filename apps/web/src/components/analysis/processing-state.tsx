import type { AnalysisStatus } from "@offerleaks/shared-types";
import { CheckCircle2, FileSearch, UploadCloud } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Represents exactly the two in-progress backend statuses ("pending",
 * "processing") as a two-step progress list, plus the received-upload
 * step that always precedes them. No stage here claims more granularity
 * than the backend actually reports.
 */
export function ProcessingState({ status }: { status: Extract<AnalysisStatus, "pending" | "processing"> }) {
  const steps = [
    { key: "received", label: "Document received", icon: UploadCloud, done: true },
    {
      key: "queued",
      label: "Queued for analysis",
      icon: FileSearch,
      done: status === "processing",
      active: status === "pending",
    },
    {
      key: "analyzing",
      label: "Reading and analyzing the offer",
      icon: FileSearch,
      done: false,
      active: status === "processing",
    },
  ] as const;

  return (
    <div className="flex flex-col items-center gap-6 py-6 text-center">
      <div className="relative flex h-20 w-20 items-center justify-center rounded-full bg-primary-50">
        <div className="absolute inset-0 animate-pulse-ring rounded-full border-2 border-primary/40" />
        <FileSearch className="h-8 w-8 text-primary-700" strokeWidth={1.75} />
      </div>

      <div className="w-full max-w-xs">
        <ol className="flex flex-col gap-3 text-left">
          {steps.map((step) => (
            <li key={step.key} className="flex items-center gap-3">
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs",
                  step.done
                    ? "border-safe bg-safe-bg text-safe"
                    : step.active
                      ? "animate-pulse-ring border-primary bg-primary-50 text-primary-700"
                      : "border-border bg-secondary text-muted-foreground",
                )}
              >
                {step.done ? <CheckCircle2 className="h-4 w-4" /> : <step.icon className="h-3.5 w-3.5" />}
              </span>
              <span className={cn("text-sm", step.done || step.active ? "font-medium text-foreground" : "text-muted-foreground")}>
                {step.label}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <p className="max-w-xs text-xs text-muted-foreground">
        This usually takes under a minute. Feel free to check back on this page — it&apos;ll update automatically.
      </p>
    </div>
  );
}
