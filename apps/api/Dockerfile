# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv is copied as a static binary rather than pip-installed -- faster,
# no extra layer for pip's own bootstrap.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependencies first, so this layer only invalidates when the lockfile
# changes, not on every source edit.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Migrations run as an explicit release-phase step (Railway/Fly release
# command, or a separate CI job) -- not baked into the container's
# default CMD, so a container can restart without silently re-running
# migrations against a database another instance is mid-migrating.
CMD ["uv", "run", "uvicorn", "offerleaks.main:app", "--host", "0.0.0.0", "--port", "8000"]
