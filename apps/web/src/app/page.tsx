import Link from "next/link";
import { AlertOctagon, FileSearch, ScanSearch, ShieldCheck, UploadCloud } from "lucide-react";

import { auth } from "@/auth";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ApiUnreachableError, getDependencyHealth, getHealth } from "@/lib/api";

const STEPS = [
  {
    icon: UploadCloud,
    title: "Upload the letter",
    description: "Add a PDF, JPEG, or PNG of the offer or internship letter you received.",
  },
  {
    icon: ScanSearch,
    title: "We read and analyze it",
    description: "OfferLeaks reads the document and checks it against known scam patterns.",
  },
  {
    icon: ShieldCheck,
    title: "Get a clear verdict",
    description: "A risk score, the red flags we found, and the reasoning behind them — in plain language.",
  },
];

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${ok ? "text-safe" : "text-risk"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-safe" : "bg-risk"}`} />
      {label}
    </span>
  );
}

export default async function Home() {
  const session = await auth();
  let apiOk = false;
  let dbOk = false;
  let redisOk = false;
  let statusError: string | null = null;

  try {
    const health = await getHealth();
    apiOk = health.status === "ok";
    const deps = await getDependencyHealth();
    dbOk = deps.database === "ok";
    redisOk = deps.redis === "ok";
  } catch (err) {
    statusError = err instanceof ApiUnreachableError ? err.message : "Unexpected error contacting the API";
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border">
        <div className="container flex h-16 items-center justify-between">
          <Logo />
          <div className="flex items-center gap-2">
            {session?.user ? (
              <Button asChild size="sm">
                <Link href="/dashboard">Go to dashboard</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/login">Sign in</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href="/register">Create account</Link>
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        <section className="container flex flex-col items-center gap-6 py-20 text-center sm:py-28">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5 text-primary-700" strokeWidth={2.25} />
            Offer &amp; internship letter scam detection
          </span>
          <h1 className="max-w-2xl text-balance font-display text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
            Know if that offer letter is real before you act on it.
          </h1>
          <p className="max-w-xl text-balance text-base text-muted-foreground sm:text-lg">
            Upload the offer letter you received. OfferLeaks reads it, checks it against known scam
            patterns, and gives you a clear, honest verdict — not a guess.
          </p>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg">
              <Link href={session?.user ? "/dashboard/upload" : "/register"}>
                <FileSearch className="h-4 w-4" />
                Check an offer letter
              </Link>
            </Button>
            {!session?.user && (
              <Button asChild variant="outline" size="lg">
                <Link href="/login">Sign in</Link>
              </Button>
            )}
          </div>
        </section>

        <section className="border-t border-border bg-secondary/40 py-16">
          <div className="container">
            <h2 className="text-center font-display text-xl font-semibold text-foreground">How it works</h2>
            <div className="mt-10 grid gap-8 sm:grid-cols-3">
              {STEPS.map((step, i) => (
                <div key={step.title} className="flex flex-col items-center gap-3 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-100 text-primary-700">
                    <step.icon className="h-6 w-6" strokeWidth={1.75} />
                  </div>
                  <h3 className="font-display text-base font-semibold text-foreground">
                    {i + 1}. {step.title}
                  </h3>
                  <p className="max-w-[22rem] text-sm text-muted-foreground">{step.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="container py-16">
          <div className="mx-auto flex max-w-lg items-start gap-3 rounded-xl border border-border bg-card p-5">
            <AlertOctagon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" strokeWidth={1.75} />
            <p className="text-sm text-muted-foreground">
              OfferLeaks gives you a risk signal based on the document you provide. It&apos;s a tool to help
              you evaluate an offer — always use your own judgment alongside it.
            </p>
          </div>
        </section>
      </main>

      <footer className="border-t border-border py-6">
        <div className="container flex flex-col items-center justify-between gap-3 text-xs text-muted-foreground sm:flex-row">
          <p>© {new Date().getFullYear()} OfferLeaks</p>
          <div className="flex items-center gap-4">
            {statusError ? (
              <StatusPill ok={false} label="Service status unavailable" />
            ) : (
              <>
                <StatusPill ok={apiOk} label="API" />
                <StatusPill ok={dbOk} label="Database" />
                <StatusPill ok={redisOk} label="Cache" />
              </>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}
