import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getEntitlementsUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /billing/me` -- see `../../credits/route.ts`
 * for why this exists (the browser never receives the raw backend access
 * token; this Route Handler runs server-side and attaches it).
 */
export async function GET(): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await getEntitlementsUpstream(session.accessToken);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
