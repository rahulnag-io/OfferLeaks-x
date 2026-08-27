import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-xl border border-risk-bg bg-risk-bg/60 px-6 py-10 text-center"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-risk-bg text-risk">
        <AlertTriangle className="h-6 w-6" strokeWidth={1.75} />
      </div>
      <h3 className="font-display text-base font-semibold text-risk-foreground">{title}</h3>
      <p className="max-w-sm text-sm text-risk-foreground/90">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}
