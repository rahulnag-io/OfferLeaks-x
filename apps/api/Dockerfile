# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Install ClamAV and the utilities required by the production startup.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        clamav \
        clamav-daemon \
        clamav-freshclam && \
    rm -rf /var/lib/apt/lists/*

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

# Configure clamd to listen on localhost:3310, matching:
# CLAMAV_HOST=localhost
# CLAMAV_PORT=3310
RUN sed -i \
        -e 's/^#TCPSocket 3310/TCPSocket 3310/' \
        -e 's/^#TCPAddr 127\.0\.0\.1/TCPAddr 127.0.0.1/' \
        /etc/clamav/clamd.conf && \
    chmod +x /app/start.sh

EXPOSE 8000

CMD ["/app/start.sh"]
