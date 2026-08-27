#!/bin/sh
set -eu

echo "Starting ClamAV database update..."

# Download/update virus definitions. Failure is logged, but we still
# allow clamd to start in case a usable database already exists.
freshclam || echo "WARNING: freshclam failed; attempting to start clamd with existing database."

echo "Starting clamd..."
clamd --config-file=/etc/clamav/clamd.conf &

echo "Waiting for ClamAV to become available..."

python - <<'PY'
import socket
import sys
import time

host = "127.0.0.1"
port = 3310
timeout_seconds = 120

deadline = time.time() + timeout_seconds

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2) as sock:
            sock.sendall(b"PING\n")
            response = sock.recv(1024)

            if b"PONG" in response:
                print("ClamAV is ready.")
                sys.exit(0)
    except OSError:
        pass

    time.sleep(2)

print("ERROR: ClamAV did not become ready within 120 seconds.", file=sys.stderr)
sys.exit(1)
PY

echo "Starting OfferLeaks API..."

exec uv run uvicorn offerleaks.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}"