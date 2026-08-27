#!/bin/sh
set -eu

echo "=== OfferLeaks startup ==="

echo "ClamAV configuration:"
echo "  Host: 127.0.0.1"
echo "  Port: 3310"

# Ensure ClamAV directories exist and have the expected ownership.
mkdir -p /var/lib/clamav
chown -R clamav:clamav /var/lib/clamav /var/run/clamav 2>/dev/null || true

echo "=== Updating ClamAV virus definitions ==="

# freshclam normally runs as the clamav user. Run the update before
# starting clamd so the daemon loads the latest available definitions.
freshclam || echo "WARNING: freshclam failed; continuing with existing definitions if available."

echo "=== Starting ClamAV daemon ==="

clamd --config-file=/etc/clamav/clamd.conf &
CLAMD_PID=$!

echo "clamd started with PID: $CLAMD_PID"

echo "=== Waiting for ClamAV readiness ==="

python - <<'PY'
import socket
import sys
import time

host = "127.0.0.1"
port = 3310
timeout_seconds = 180

deadline = time.time() + timeout_seconds

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=3) as sock:
            sock.sendall(b"PING\n")
            response = sock.recv(1024)

            if b"PONG" in response:
                print("ClamAV is ready.")
                sys.exit(0)

            print(f"ClamAV returned unexpected response: {response!r}")

    except OSError as exc:
        print(f"Waiting for ClamAV: {exc}")

    time.sleep(2)

print("ERROR: ClamAV did not become ready within 180 seconds.", file=sys.stderr)
sys.exit(1)
PY

echo "=== ClamAV ready ==="
echo "=== Starting OfferLeaks API ==="

exec uv run uvicorn offerleaks.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}"