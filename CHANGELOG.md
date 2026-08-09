# Changelog

All notable changes to this project will be documented in this file.

The changelog records what was introduced, changed, fixed, deferred, or intentionally excluded in each release. The project architecture, technology choices, security model, and roadmap are maintained in [`README.md`](./README.md).

The format is based on **Keep a Changelog**, and this project follows **Semantic Versioning (SemVer)**.

---

## [Unreleased]

Changes planned for the next release will be recorded here.

### Planned

- Authentication foundation
- Email/password authentication
- OAuth integration
- Session management
- Initial RBAC scaffold

---

## [0.1.0] — Foundation

**Release:** `v0.1.0`
**Milestone:** Foundation
**Status:** Complete

The first development release establishes the technical foundation for OfferLeaks. The goal of this release was to create a working system in which the frontend, backend, database, cache, migrations, and CI are wired together and verified before product functionality is introduced.

### Added

#### Monorepo

* Established the Turborepo monorepo structure.
* Added `apps/api` for the FastAPI backend.
* Added `apps/web` for the Next.js frontend.
* Added shared packages for TypeScript types, ESLint configuration, and TypeScript configuration.
* Configured npm workspaces and Turborepo tasks.

#### Backend

* Added the initial FastAPI application.
* Added `GET /health` liveness endpoint.
* Added `GET /health/dependencies` dependency health endpoint.
* Dependency health reports PostgreSQL and Redis independently as `ok` or `error`.
* Added Pydantic-based application settings as the backend configuration source of truth.
* Configured Alembic to consume database configuration from the application settings.
* Established the initial backend layers:

  * `api`
  * `services`
  * `repositories`
  * `providers`
  * `models`
  * `core`

#### Database and Cache

* Added PostgreSQL development infrastructure.
* Added Redis development infrastructure.
* Added Docker Compose configuration for local services.
* Added Alembic migration infrastructure.
* Added the baseline migration with no application tables yet.

#### Frontend

* Added the initial Next.js application.
* Added the foundation home page.
* Added frontend → API connectivity.
* Added live status indicators for:

  * Web → API
  * API → PostgreSQL
  * API → Redis
* Added graceful API-unavailable handling so the frontend does not crash when the backend cannot be reached.

#### Security and Configuration

* Scoped CORS to the configured frontend origin instead of allowing `*`.
* Added environment-driven configuration rather than hard-coding environment-specific values.
* Established the foundation for the security controls that will be introduced in later milestones.

#### CI

* Added the initial CI pipeline.
* CI runs the project quality gates through Turborepo:

  * lint
  * type-check
  * test
  * build
* CI provisions real PostgreSQL and Redis services for backend verification rather than relying only on mocks.

### Verification

The foundation was verified through an independent end-to-end run rather than only by inspecting the source code.

Verified successfully:

* Monorepo structure and workspace resolution.
* Backend dependency installation with `uv sync`.
* Frontend dependency installation with `npm install`.
* Alembic migration execution.
* `GET /health` returning HTTP 200.
* Independent PostgreSQL and Redis dependency health reporting.
* Redis failure correctly affecting only the Redis health status.
* Next.js development server startup.
* Next.js production build.
* Frontend rendering of all three connection statuses.
* Graceful frontend behavior when the API is unavailable.
* CORS preflight behavior.
* Turborepo lint, type-check, and build tasks.
* Backend tests: **2/2 passing**.
* CI configuration covering the intended foundation checks.

### Known Gaps

The following items are intentionally carried into the next development cycle and do not invalidate the `v0.1.0` foundation:

1. **Frontend tests**
   No meaningful frontend test currently exists. `turbo run test` succeeds because there is no frontend test suite yet. A minimal frontend smoke/component test is required before more product functionality is layered on top.

2. **Next.js dependency upgrade**
   The current Next.js dependency chain has reported high-severity transitive advisories involving `postcss` / `sharp`. The upgrade to the appropriate Next.js version should be handled deliberately rather than through `npm audit fix --force`.

3. **ESLint configuration**
   Plain TypeScript packages such as `shared-types` currently rely on the Next.js-oriented ESLint configuration and produce a spurious warning. A suitable base configuration should be introduced.

4. **Python async test configuration**
   The pytest configuration currently specifies `asyncio_mode = "auto"` while tests use the `@pytest.mark.anyio` marker. The project should standardize on one async testing approach and remove the unused configuration.

5. **Docker verification**
   The Docker Compose and API Dockerfile were validated structurally, but an actual `docker compose up` verification remains to be performed in an environment with Docker available.

6. **Turborepo API build caching**
   The API `build.outputs` configuration should be corrected so Turbo does not treat a task as cacheable when the task produces no corresponding output directory.

7. **Shared health status type**
   The shared `HealthStatus` type is currently wider than the backend's actual health response. It should be tightened to the values the backend actually exposes before additional shared types are introduced.

### Deliberate Scope Boundaries

The following were intentionally **not** included in `v0.1.0`:

* Authentication and sessions.
* RBAC.
* User accounts.
* Application data models.
* Document uploads.
* OCR.
* AI analysis and verdicts.
* Credit system.
* Reputation system.
* Scam wall.
* Rate limiting.
* Secrets management.
* Virus/malware scanning.
* Production hardening.
* Frontend Docker deployment.

These belong to later milestones and are not considered missing Foundation functionality.

### Architecture Decisions Noted During Foundation

* The backend uses layered/hexagonal-style boundaries from the beginning so later product functionality has defined locations for domain logic, persistence, external providers, and API concerns.
* The API is containerized for local/deployment consistency.
* The Next.js application is intended for Vercel deployment and therefore does not currently have its own Dockerfile.
* PostgreSQL and Redis are provisioned locally through Docker Compose.
* The baseline database migration intentionally creates no application tables.

### Next

The next milestone builds product functionality on top of this foundation, beginning with authentication and the associated user/session model.

---

## Release Versioning

OfferLeaks uses [Semantic Versioning](https://semver.org/) for software releases.

Development milestones and release versions are related but are not the same thing:

```text
M1 — Foundation
        ↓
     v0.1.0

M2 — Authentication
        ↓
     v0.2.0

M3 — Upload → OCR → AI Verdict
        ↓
     v0.3.0
```

The roadmap in [Roadmap](./docs/roadmap.md) describes product milestones; this file records the implementation history of released versions.
