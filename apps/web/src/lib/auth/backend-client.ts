/**
 * Server-only client for the backend's `/auth` endpoints.
 *
 * Only ever imported from `src/auth.ts` (NextAuth config, runs server-side)
 * and Server Actions -- never from a Client Component. Follows the same
 * server-side-fetch convention as `lib/api.ts`: `API_URL` has no
 * `NEXT_PUBLIC_` prefix, so it isn't in the browser bundle, and the
 * browser never talks to the FastAPI backend directly.
 */

import type { TokenResponse } from "@offerleaks/shared-types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET;

export class EmailAlreadyRegisteredError extends Error {
  constructor() {
    super("An account with this email already exists");
    this.name = "EmailAlreadyRegisteredError";
  }
}

export async function registerUser(
  email: string,
  password: string,
  fullName: string | null,
): Promise<TokenResponse> {
  const response = await fetch(`${API_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name: fullName }),
    cache: "no-store",
  });

  if (response.status === 409) {
    throw new EmailAlreadyRegisteredError();
  }
  if (!response.ok) {
    throw new Error(`Registration failed: ${response.status}`);
  }

  return (await response.json()) as TokenResponse;
}

/** Returns `null` on invalid credentials (401) so `authorize()` can reject cleanly. */
export async function loginUser(email: string, password: string): Promise<TokenResponse | null> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Login failed: ${response.status}`);
  }

  return (await response.json()) as TokenResponse;
}

/** Returns `null` if the refresh token is invalid, expired, or already used. */
export async function refreshTokens(refreshToken: string): Promise<TokenResponse | null> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });

  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Token refresh failed: ${response.status}`);
  }

  return (await response.json()) as TokenResponse;
}

export async function logoutUser(refreshToken: string): Promise<void> {
  await fetch(`${API_URL}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  }).catch(() => {
    // Best-effort: the NextAuth session cookie is already gone by the time
    // this runs, so a failed revocation here doesn't leave anything reachable.
  });
}

/**
 * Find-or-create a user from a Google identity, gated by a shared secret
 * only this server holds (see architecture.md §0.13 and
 * `offerleaks.api.routers.auth._verify_internal_secret`).
 */
export async function googleOauthUpsert(
  subject: string,
  email: string,
  fullName: string | null,
): Promise<TokenResponse | null> {
  if (!INTERNAL_API_SECRET) {
    throw new Error("INTERNAL_API_SECRET is not configured");
  }

  const response = await fetch(`${API_URL}/auth/oauth/google`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Secret": INTERNAL_API_SECRET,
    },
    body: JSON.stringify({ subject, email, full_name: fullName }),
    cache: "no-store",
  });

  if (!response.ok) {
    return null;
  }

  return (await response.json()) as TokenResponse;
}
