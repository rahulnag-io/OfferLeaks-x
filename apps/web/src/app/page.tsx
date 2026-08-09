import { ApiUnreachableError, getDependencyHealth, getHealth } from "@/lib/api";

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${
        ok
          ? "bg-emerald-100 text-emerald-800"
          : "bg-red-100 text-red-800"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
      />
      {label}
    </span>
  );
}

export default async function Home() {
  let apiOk = false;
  let apiVersion: string | null = null;
  let dbOk = false;
  let redisOk = false;
  let error: string | null = null;

  try {
    const health = await getHealth();
    apiOk = health.status === "ok";
    apiVersion = health.version;

    const deps = await getDependencyHealth();
    dbOk = deps.database === "ok";
    redisOk = deps.redis === "ok";
  } catch (err) {
    error =
      err instanceof ApiUnreachableError
        ? err.message
        : "Unexpected error contacting the API";
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">OfferLeaks</h1>
        <p className="mt-2 text-slate-500">
          Version 1 — Foundation. This page is proof the web app can reach
          the API, and the API can reach its data layer.
        </p>
      </div>

      <div className="w-full rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-sm font-medium uppercase tracking-wide text-slate-400">
          System status
        </h2>

        {error ? (
          <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700">
            <p className="font-medium">Could not reach the API.</p>
            <p className="mt-1 text-red-600">{error}</p>
            <p className="mt-2 text-red-500">
              Is the FastAPI dev server running on the URL configured in
              <code className="mx-1 rounded bg-red-100 px-1">API_URL</code>?
            </p>
          </div>
        ) : (
          <dl className="space-y-3">
            <div className="flex items-center justify-between">
              <dt className="text-slate-600">
                Web → API{" "}
                {apiVersion && (
                  <span className="text-slate-400">(v{apiVersion})</span>
                )}
              </dt>
              <dd>
                <StatusPill ok={apiOk} label={apiOk ? "Connected" : "Down"} />
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-600">API → PostgreSQL</dt>
              <dd>
                <StatusPill ok={dbOk} label={dbOk ? "Connected" : "Down"} />
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-600">API → Redis</dt>
              <dd>
                <StatusPill
                  ok={redisOk}
                  label={redisOk ? "Connected" : "Down"}
                />
              </dd>
            </div>
          </dl>
        )}
      </div>
    </main>
  );
}
