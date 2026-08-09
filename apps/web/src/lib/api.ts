import type { DependencyHealth, HealthStatus } from "@offerleaks/shared-types";

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
