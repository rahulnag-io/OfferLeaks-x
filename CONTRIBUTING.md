# Contributing to OfferLeaks

> This project is in early development (`v0.1.0`, Foundation stage). This guide is intentionally minimal for now and will expand as the contributor process formalizes.

## Before You Start

- Check [Roadmap](./docs/roadmap.md) for the current milestone — contributions aligned with it are easiest to review.
- Check open issues before starting work. If nothing exists for what you want to do, open an issue first to discuss the approach.

## Development Setup

See [Getting Started](./docs/getting-started.md).

## Coding Standards

- **Python (`apps/api`):** `ruff` for linting, `mypy` for type-checking. Follow the existing layering — see [Architecture](./docs/architecture.md).
- **TypeScript (`apps/web`, `packages/*`):** ESLint via the shared config in `packages/eslint-config`.
- Run through Turborepo: `turbo run lint`, `turbo run type-check`, `turbo run test`, `turbo run build`.

## Submitting a Pull Request

1. Fork the repo and branch off `main`.
2. Make your change, following the standards above.
3. Ensure lint, type-check, tests, and build all pass.
4. Open a PR describing the change and its motivation.

## Security Issues

Don't open a public issue — see [SECURITY.md](./SECURITY.md).
