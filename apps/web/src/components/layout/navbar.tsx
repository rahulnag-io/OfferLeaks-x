"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { NAV_LINKS } from "@/components/layout/nav-links";

export function Navbar({
  userLabel,
  signOutSlot,
}: {
  userLabel: string;
  signOutSlot: React.ReactNode;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="container flex h-16 items-center justify-between">
        <div className="flex items-center gap-8">
          <Logo href="/dashboard" />
          <nav className="hidden items-center gap-1 md:flex">
            {NAV_LINKS.map((link) => {
              const active =
                link.href === "/dashboard" ? pathname === link.href : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-primary-50 text-primary-700"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <link.icon className="h-4 w-4" strokeWidth={2} />
                  {link.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="hidden items-center gap-3 md:flex">
          <span className="text-sm text-muted-foreground">{userLabel}</span>
          {signOutSlot}
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </Button>
      </div>

      {open && (
        <div className="border-t border-border bg-background md:hidden">
          <nav className="container flex flex-col gap-1 py-3">
            {NAV_LINKS.map((link) => {
              const active =
                link.href === "/dashboard" ? pathname === link.href : pathname.startsWith(link.href);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setOpen(false)}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium",
                    active ? "bg-primary-50 text-primary-700" : "text-foreground hover:bg-secondary",
                  )}
                >
                  <link.icon className="h-4 w-4" strokeWidth={2} />
                  {link.label}
                </Link>
              );
            })}
            <div className="mt-2 flex items-center justify-between border-t border-border pt-3">
              <span className="text-sm text-muted-foreground">{userLabel}</span>
              {signOutSlot}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
