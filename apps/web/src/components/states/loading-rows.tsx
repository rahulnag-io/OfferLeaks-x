import { Skeleton } from "@/components/ui/skeleton";

export function LoadingRows({ count = 3 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-4" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-1/4" />
            </div>
            <Skeleton className="h-8 w-20 rounded-lg" />
          </div>
        </div>
      ))}
      <span className="sr-only" role="status">
        Loading…
      </span>
    </div>
  );
}
