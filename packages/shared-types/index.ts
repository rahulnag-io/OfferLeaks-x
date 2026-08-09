/**
 * Shared TypeScript types, mirrored conceptually with the backend's
 * Pydantic schemas (see apps/api/src/schemas). Kept intentionally tiny
 * in Version 1 -- grows alongside each vertical slice.
 */

export interface HealthStatus {
  status: "ok" | "degraded" | "error";
  service: string;
  version: string;
}

export interface DependencyHealth {
  database: "ok" | "error";
  redis: "ok" | "error";
}
