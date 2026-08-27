import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { getAnalysisUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `GET /analyses/{id}` -- see `../route.ts` for why
 * this exists (the browser polls this, never the backend directly, so it
 * never needs the raw access token).
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
  const upstream = await getAnalysisUpstream(session.accessToken, id);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
