import type { DependencyHealth, HealthStatus, ReportCreateRequest, User } from "@offerleaks/shared-types";

// Server-side only: this runs in the Next.js server runtime (route handlers,
// server components), never shipped to the browser bundle, so it does not
// need the NEXT_PUBLIC_ prefix. Browser-facing API calls (added once auth
// exists) will go through a separate NEXT_PUBLIC_API_URL + a client-side
// fetch wrapper.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export class ApiUnreachableError extends Error {
  constructor(cause: unknown) {
    super("Could not reach the OfferLeaks API");
    this.name = "ApiUnreachableError";
    this.cause = cause;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      // Health checks should never be cached by Next's fetch cache.
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }

  if (!response.ok) {
    throw new Error(`API request to ${path} failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}

export function getDependencyHealth(): Promise<DependencyHealth> {
  return apiFetch<DependencyHealth>("/health/dependencies");
}

/**
 * Fetches the authenticated user, proving the full Version 2 loop: a
 * token minted by NextAuth's credentials/Google flow, independently
 * verified by the backend with no shared state but the JWT itself.
 */
export function getCurrentUser(accessToken: string): Promise<User> {
  return apiFetch<User>("/users/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

/**
 * Server-only proxy calls for the Version 3 upload/analysis endpoints.
 *
 * Unlike `apiFetch`, these return the raw backend `Response` instead of
 * decoding-or-throwing: the Route Handlers under `app/api/analyses/*`
 * (see architecture.md §0.13's client-facing-token concern, addressed by
 * never exposing `session.accessToken` to the browser -- see `auth.ts`)
 * relay the backend's status code and JSON body back to the browser
 * as-is. The backend is the single source of truth for validation/error
 * responses (413/415/422/503/404/...); this layer never re-interprets
 * them, it just adds the access token the browser never sees.
 */
export async function createAnalysisUpstream(
  accessToken: string,
  formData: FormData,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/analyses`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      body: formData,
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

export async function getAnalysisUpstream(
  accessToken: string,
  analysisId: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/analyses/${encodeURIComponent(analysisId)}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /analyses` (Version 5 dashboard/
 * history). `queryString` is forwarded as-is (limit/offset/status) --
 * the backend is the only place that validates/clamps those, this layer
 * never re-interprets them, matching the convention above.
 */
export async function listAnalysesUpstream(
  accessToken: string,
  queryString: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/analyses${queryString}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `POST /analyses/{id}/recheck` (Version 5).
 * No body -- the backend derives everything it needs (owner, stored
 * file, current prompt version) from the source analysis itself.
 */
export async function recheckAnalysisUpstream(
  accessToken: string,
  analysisId: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/analyses/${encodeURIComponent(analysisId)}/recheck`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /credits/me` (Version 4). Same pattern
 * as `getAnalysisUpstream`/`createAnalysisUpstream` above: the raw
 * backend response is relayed as-is, the browser never sees the access
 * token, and the backend's balance is the only thing ever displayed --
 * this call never sends or derives a balance client-side.
 */
export async function getCreditsUpstream(accessToken: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}/credits/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /billing/plans` (M6). Public on the
 * backend (no auth required to see pricing), but still proxied through
 * here rather than called directly from the browser, for the same
 * same-origin-only reason every other backend call in this file is:
 * the frontend never hardcodes or exposes the backend's own base URL to
 * client code.
 */
export async function listPlansUpstream(): Promise<Response> {
  try {
    return await fetch(`${API_URL}/billing/plans`, { cache: "no-store" });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /billing/me` (M6) -- the current
 * user's plan, subscription status, and this month's usage against it.
 * Same token-never-reaches-the-browser pattern as `getCreditsUpstream`.
 */
export async function getEntitlementsUpstream(accessToken: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}/billing/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `POST /billing/subscribe` (M6). Returns a
 * Razorpay-hosted checkout URL the browser is redirected to -- this
 * layer never touches card details, matching §0.11's "sensitive payment
 * data never passes through our own servers."
 */
export async function createSubscriptionUpstream(
  accessToken: string,
  planKey: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/billing/subscribe`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ plan_key: planKey }),
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/** Server-only proxy call for `POST /billing/cancel` (M6). */
export async function cancelSubscriptionUpstream(accessToken: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}/billing/cancel`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `POST /reports` (M8). Same relay-as-is
 * pattern as `createAnalysisUpstream` -- the backend is the only place
 * that validates the submission (target/company/analysis context,
 * reasons, description length), this layer just forwards the body and
 * adds the token the browser never sees.
 */
export async function createReportUpstream(
  accessToken: string,
  body: ReportCreateRequest,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/reports`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/** Server-only proxy call for `GET /reports/mine` (M8). */
export async function listMyReportsUpstream(
  accessToken: string,
  queryString: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/reports/mine${queryString}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /reports/{id}` (M8, Pro-gated on the
 * backend -- this layer never re-derives that gate, it only relays the
 * backend's 200/402/404 as-is).
 */
export async function getReportDetailUpstream(
  accessToken: string,
  reportId: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/reports/${encodeURIComponent(reportId)}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /analytics/me` (M8). Free for every
 * plan on the backend -- no entitlement check needed at this layer
 * either.
 */
export async function getAnalyticsUpstream(accessToken: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}/analytics/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}

/**
 * Server-only proxy call for `GET /comparison` (M8, Pro-gated on the
 * backend). `queryString` carries `analysis_id_a`/`analysis_id_b`,
 * forwarded as-is -- same "backend validates, this layer relays"
 * convention as `listAnalysesUpstream`.
 */
export async function compareOffersUpstream(
  accessToken: string,
  queryString: string,
): Promise<Response> {
  try {
    return await fetch(`${API_URL}/comparison${queryString}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
  } catch (err) {
    throw new ApiUnreachableError(err);
  }
}
