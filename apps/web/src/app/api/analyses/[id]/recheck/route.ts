import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { recheckAnalysisUpstream } from "@/lib/api";

/**
 * Same-origin proxy for `POST /analyses/{id}/recheck` (Version 5) -- see
 * `../../route.ts` for why this pattern exists (the browser never needs
 * the raw access token).
 */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  const { id } = await params;
  const upstream = await recheckAnalysisUpstream(session.accessToken, id);
  const body = await upstream.json().catch(() => null);
  return NextResponse.json(body, { status: upstream.status });
}
