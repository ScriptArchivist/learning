#!/usr/bin/env bash
set -euo pipefail

echo "== Video Platform local K8S doctor =="

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: command not found: $1"
    exit 1
  }
}

need docker
need minikube
need kubectl

echo
echo "== Docker =="
docker info >/dev/null
echo "OK: Docker is running"

echo
echo "== Minikube status =="
minikube status || true

echo
echo "== Kubernetes nodes =="
kubectl get nodes || true

echo
echo "== Ingress addon =="
kubectl get pods -n ingress-nginx || true

echo
echo "== Project pods =="
kubectl get pods || true

echo
echo "== Problem pods =="
kubectl get pods | grep -E 'ErrImagePull|ImagePullBackOff|CrashLoopBackOff|Error' || echo "OK: no obvious problem pods"

echo
echo "== Local images inside Minikube Docker =="
eval "$(minikube docker-env)"
docker images | grep -E 'learning-app-backend|learning-app-frontend|learning-app-ingest' || true

echo
echo "== Services =="
kubectl get svc || true

echo
echo "== Ingress =="
kubectl get ingress -o wide || true

echo
echo "== Host ports =="
sudo ss -lntp | grep -E ':80|:443|:30000|:30001|:30002|:30003|:30004|:30005|:30006|:31935|:32169' || true

echo
echo "== Minikube docker published ports =="
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep minikube || true

echo
echo "== LAN IP =="
hostname -I

echo
echo "== API checks through Minikube IP =="
MINIKUBE_IP="$(minikube ip)"
curl -fsS "http://${MINIKUBE_IP}:30002/docs" >/dev/null && echo "OK: identity-service"
curl -fsS "http://${MINIKUBE_IP}:30000/docs" >/dev/null && echo "OK: web"
curl -fsS "http://${MINIKUBE_IP}:30004/docs" >/dev/null && echo "OK: video-api"

echo
echo "Doctor finished."