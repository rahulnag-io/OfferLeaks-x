import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/auth";
import { compareOffersUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /comparison` (M8, Pro-gated on the
 * backend). `analysis_id_a`/`analysis_id_b` are forwarded as-is; the
 * backend validates ownership and returns 402/400/404 as appropriate,
 * relayed here unchanged.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await compareOffersUpstream(session.accessToken, request.nextUrl.search);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
