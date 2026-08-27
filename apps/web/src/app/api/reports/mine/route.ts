import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/auth";
import { listMyReportsUpstream } from "@/lib/api";

/** Same-origin proxy for `GET /reports/mine` (M8). */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await listMyReportsUpstream(session.accessToken, request.nextUrl.search);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
