import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

import { Logo } from "@/components/brand/logo";

const TRUST_POINTS = [
  "Upload a PDF or photo of the offer letter.",
  "Get a risk score, red flags, and the reasoning behind them.",
  "Decide with the facts in front of you — not just a gut feeling.",
];

export function AuthShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col justify-center px-6 py-16 sm:px-10 lg:px-16">
        <div className="mx-auto w-full max-w-sm">
          <Logo className="mb-10" />
          <div className="mb-8">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{description}</p>
          </div>
          {children}
        </div>
      </div>

      <div className="relative hidden overflow-hidden bg-primary-700 lg:block">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,hsl(var(--primary))_0%,transparent_55%)] opacity-70" />
        <div className="relative flex h-full flex-col justify-center px-16 text-primary-foreground">
          <ShieldCheck className="h-10 w-10" strokeWidth={1.5} />
          <p className="mt-6 max-w-sm font-display text-2xl font-medium leading-snug">
            Know if that offer letter is real before you act on it.
          </p>
          <ul className="mt-10 flex flex-col gap-4">
            {TRUST_POINTS.map((point) => (
              <li key={point} className="flex items-start gap-3 text-sm text-primary-foreground/85">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
                {point}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
