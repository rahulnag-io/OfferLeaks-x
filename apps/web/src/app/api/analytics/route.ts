import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getAnalyticsUpstream } from "@/lib/api";

/** Same-origin proxy for `GET /analytics/me` (M8). Free for every plan. */
export async function GET(): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await getAnalyticsUpstream(session.accessToken);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
