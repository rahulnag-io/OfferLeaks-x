#!/bin/sh
set -eu

echo "=== OfferLeaks startup ==="
echo "=== Starting OfferLeaks API ==="

exec uv run uvicorn offerleaks.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}"
