import type { ReportCreateRequest } from "@offerleaks/shared-types";
import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { createReportUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `POST /reports` (M8) -- same token-hiding
 * rationale as every other proxy in `app/api/*`: the "Report this
 * company" dialog is a Client Component and never receives the raw
 * backend access token.
 */
export async function POST(request: Request): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const payload = (await request.json().catch(() => null)) as ReportCreateRequest | null;
  if (!payload) {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 });
  }

  const upstream = await createReportUpstream(session.accessToken, payload);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
