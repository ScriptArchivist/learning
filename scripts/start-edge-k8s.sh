#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDGE_DIR="${ROOT_DIR}/deploy/edge"
CONTAINER_NAME="learning-app-edge-proxy"

echo "[edge] Checking Minikube availability..."
minikube ip >/dev/null

echo "[edge] Preparing K8S edge config..."
cp "${EDGE_DIR}/nginx.k8s.conf" "${EDGE_DIR}/active.conf"

echo "[edge] Removing old container if exists..."
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

echo "[edge] Starting K8S edge proxy on host network..."
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network host \
  -v "${EDGE_DIR}/active.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.25-alpine

echo "[edge] K8S edge proxy started."
echo "[edge] Health:  http://192.168.1.12/healthz"
echo "[edge] Docs:    http://192.168.1.12/docs"
echo "[edge] Frontend direct: http://192.168.49.2:30001/login"