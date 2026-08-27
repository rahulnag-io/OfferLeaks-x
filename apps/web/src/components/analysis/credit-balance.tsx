import { Coins } from "lucide-react";

import { cn } from "@/lib/utils";

export function CreditBalanceBadge({ balance, costPerAnalysis }: { balance: number; costPerAnalysis: number }) {
  const low = balance < costPerAnalysis;

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 rounded-xl border px-4 py-3 text-sm",
        low ? "border-caution-bg bg-caution-bg text-caution-foreground" : "border-border bg-card text-foreground",
      )}
    >
      <span className="flex items-center gap-2 font-medium">
        <Coins className="h-4 w-4" strokeWidth={2} />
        {balance} credit{balance === 1 ? "" : "s"} remaining
      </span>
      <span className="text-xs text-muted-foreground">Each scan costs {costPerAnalysis}</span>
    </div>
  );
}
