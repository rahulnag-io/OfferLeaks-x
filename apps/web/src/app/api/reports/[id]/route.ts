import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getReportDetailUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /reports/{id}` (M8, Pro-gated on the
 * backend) -- this route relays the backend's 200/402/404 as-is, it
 * never re-derives the gate itself.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const { id } = await params;
  const upstream = await getReportDetailUpstream(session.accessToken, id);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
