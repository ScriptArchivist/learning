#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="learning-app-edge-proxy"

echo "[edge] Stopping edge proxy..."
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
echo "[edge] Edge proxy stopped."