# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv is copied as a static binary rather than pip-installed.
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

RUN chmod +x /app/start.sh

EXPOSE 8000

CMD ["/app/start.sh"]
