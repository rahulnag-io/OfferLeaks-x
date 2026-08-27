import type { AnalysisStatus } from "@offerleaks/shared-types";
import { CheckCircle2, Clock, type LucideIcon, Loader2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { STATUS_BADGE_VARIANT, STATUS_LABEL } from "@/lib/risk";

const STATUS_ICON: Record<AnalysisStatus, LucideIcon> = {
  pending: Clock,
  processing: Loader2,
  complete: CheckCircle2,
  failed: XCircle,
  needs_manual_review: ShieldAlert,
};

export function AnalysisStatusBadge({ status }: { status: AnalysisStatus }) {
  const Icon = STATUS_ICON[status];
  return (
    <Badge variant={STATUS_BADGE_VARIANT[status]}>
      <Icon className={`h-3 w-3 ${status === "processing" ? "animate-spin" : ""}`} strokeWidth={2.5} />
      {STATUS_LABEL[status]}
    </Badge>
  );
}
