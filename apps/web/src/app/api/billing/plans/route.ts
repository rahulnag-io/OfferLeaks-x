import { NextResponse } from "next/server";

import { listPlansUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /billing/plans` -- public on the backend
 * (no auth), proxied for the same same-origin-only reason as every
 * other Route Handler in `app/api/*` (see `../credits/route.ts`).
 */
export async function GET(): Promise<NextResponse> {
  const upstream = await listPlansUpstream();
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
