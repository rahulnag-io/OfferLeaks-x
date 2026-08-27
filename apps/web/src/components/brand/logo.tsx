import Link from "next/link";
import { ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";

export function Logo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex items-center gap-2 font-display text-lg font-semibold tracking-tight text-foreground",
        className,
      )}
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <ShieldCheck className="h-[18px] w-[18px]" strokeWidth={2.25} />
      </span>
      OfferLeaks
    </Link>
  );
}
