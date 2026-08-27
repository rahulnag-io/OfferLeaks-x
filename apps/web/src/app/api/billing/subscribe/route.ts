import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { createSubscriptionUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `POST /billing/subscribe` (M6). Unlike the
 * no-body proxies elsewhere in `app/api/*`, this one reads a JSON body
 * from the browser (`{ plan_key }`) and forwards it -- the plan key
 * itself isn't sensitive, so passing it through is fine; what this
 * layer still guarantees is that the access token attached to the
 * upstream request never came from client-readable state.
 */
export async function POST(request: Request): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const body = (await request.json().catch(() => null)) as { plan_key?: string } | null;
  if (!body?.plan_key) {
    return NextResponse.json({ detail: "plan_key is required" }, { status: 400 });
  }

  const upstream = await createSubscriptionUpstream(session.accessToken, body.plan_key);
  const upstreamBody = await upstream.json().catch(() => null);
  return NextResponse.json(upstreamBody, { status: upstream.status });
}
