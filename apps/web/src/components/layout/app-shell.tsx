import type { ReactNode } from "react";

import { Navbar } from "@/components/layout/navbar";

export function AppShell({
  userLabel,
  signOutSlot,
  children,
}: {
  userLabel: string;
  signOutSlot: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Navbar userLabel={userLabel} signOutSlot={signOutSlot} />
      <main className="container flex-1 py-8 md:py-10">{children}</main>
      <footer className="border-t border-border py-6">
        <div className="container flex flex-col items-center justify-between gap-2 text-xs text-muted-foreground sm:flex-row">
          <p>OfferLeaks does not store your decision for you — it gives you the facts.</p>
          <p>Verdicts are a risk signal, not legal or employment advice.</p>
        </div>
      </footer>
    </div>
  );
}
