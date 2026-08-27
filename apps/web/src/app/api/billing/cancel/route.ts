import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { cancelSubscriptionUpstream } from "@/lib/api";

/** Same-origin proxy for `POST /billing/cancel` (M6). */
export async function POST(): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const upstream = await cancelSubscriptionUpstream(session.accessToken);
  if (upstream.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
