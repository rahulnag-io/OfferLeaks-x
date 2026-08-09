# Getting Started

This guide covers setting up OfferLeaks locally for development.

The current release is **v0.1.0 — Foundation**. The repository currently provides the monorepo, application scaffolding, local infrastructure, and development tooling. The OCR, AI verdict, reputation, and other product capabilities are introduced in later milestones.

## Prerequisites

Install the following:

* [Node.js](https://nodejs.org/) — JavaScript/TypeScript runtime
* [uv](https://docs.astral.sh/uv/) — Python package and environment manager
* [Docker](https://docs.docker.com/get-docker/) — local PostgreSQL and Redis services
* [Git](https://git-scm.com/) — version control and repository management

PostgreSQL and Redis do not need to be installed separately; they are started through Docker Compose.

## Installation

Clone the repository and enter the project directory:

```bash
git clone https://github.com/rahulnag-io/OfferLeaks.git
cd OfferLeaks
```

Install JavaScript/TypeScript dependencies:

```bash
npm install
```

Install Python dependencies for the API:

```bash
cd apps/api
uv sync
cd ../..
```

Start the local infrastructure:

```bash
docker compose up -d
```

Create the local environment files:

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

Run database migrations:

```bash
cd apps/api
uv run alembic upgrade head
cd ../..
```

## Running in Development

From the repository root:

```bash
npm run dev
```

Turborepo starts the web and API applications in parallel.

| Service           | URL                        |
| ----------------- | -------------------------- |
| Web               | http://localhost:3000      |
| API               | http://localhost:8000      |
| API documentation | http://localhost:8000/docs |

The API documentation is generated automatically by FastAPI through OpenAPI.

## Configuration

Local configuration is provided through environment variables.

Copy the example files during setup:

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
```

Only configure variables required by the current milestone. Credentials for future services such as the AI provider, OCR provider, object storage, and OAuth integrations will be documented when those integrations become part of the active milestone.

Never commit real credentials or secrets to the repository.

## Local Services

Docker Compose currently provides the local infrastructure required by the foundation:

* PostgreSQL
* Redis

Check running services with:

```bash
docker compose ps
```

Stop the services with:

```bash
docker compose down
```

To stop the services and remove their local volumes:

```bash
docker compose down -v
```

> Removing volumes deletes the local database data.

## Troubleshooting

### Ports are already in use

The development servers use:

* Web: `3000`
* API: `8000`

PostgreSQL and Redis use the ports configured in `docker-compose.yml`.

If one of these ports is already occupied, stop the conflicting service or update the corresponding local configuration.

### Database migration errors

Make sure PostgreSQL is running:

```bash
docker compose ps
```

Then retry:

```bash
cd apps/api
uv run alembic upgrade head
```

### Python dependency issues

Make sure `uv` is installed and the API environment has been synchronized:

```bash
cd apps/api
uv sync
```

### Frontend dependency issues

From the repository root:

```bash
npm install
```

Then retry:

```bash
npm run dev
```

## Next Steps

* [Roadmap](./roadmap.md) — milestone-by-milestone product plan
* [Architecture](./architecture.md) — system architecture, data model, and technical decisions
* [CHANGELOG.md](../CHANGELOG.md) — history of what has actually shipped
* [CONTRIBUTING.md](../CONTRIBUTING.md) — development and contribution workflow
