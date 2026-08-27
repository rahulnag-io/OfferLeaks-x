import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/auth";
import { createAnalysisUpstream, listAnalysesUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `POST /analyses` on the backend.
 *
 * This exists specifically so a Client Component (the upload form) never
 * needs the backend's raw access token: it POSTs here instead, this
 * Route Handler runs server-side, reads the session via `auth()`, and
 * attaches the `Authorization` header itself. The browser never sees the
 * token that would otherwise have to flow through client-side JS to
 * reach the backend directly (see the Version 2 review's Medium finding
 * on `session.accessToken` exposure via `/api/auth/session` -- this
 * route deliberately doesn't add to that surface for Version 3's new
 * client-side data fetching).
 */
export async function POST(request: Request): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const formData = await request.formData();
  const upstream = await createAnalysisUpstream(session.accessToken, formData);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}

/**
 * Same-origin proxy for `GET /analyses` (Version 5 dashboard/history) --
 * same token-hiding rationale as `POST` above. The query string
 * (limit/offset/status) is forwarded as-is; the backend validates it.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await listAnalysesUpstream(session.accessToken, request.nextUrl.search);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
