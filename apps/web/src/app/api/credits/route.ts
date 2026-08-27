import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getCreditsUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /credits/me` -- see `../analyses/route.ts`
 * for why this exists (the browser never receives the raw backend access
 * token; this Route Handler runs server-side and attaches it).
 *
 * This is read-only and purely a display concern: the balance shown here
 * is never trusted by the backend for anything, and the backend re-checks
 * eligibility from scratch on every `POST /analyses` regardless of what
 * this endpoint last returned (see `AnalysisUploader`'s handling of a 402
 * response for the case where the two have gone stale relative to each
 * other).
 */
export async function GET(): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await getCreditsUpstream(session.accessToken);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
