#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/projects/learning_app}"
FRONTEND_DIR="${FRONTEND_DIR:-$HOME/projects/web_app}"

CPUS="${CPUS:-4}"
MEMORY="${MEMORY:-7900}"

echo "== Video Platform local K8S start =="

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
echo "== Starting Minikube =="

if ! minikube status >/dev/null 2>&1; then
  minikube start \
    --driver=docker \
    --cpus="$CPUS" \
    --memory="$MEMORY" \
    --ports=80:80 \
    --ports=443:443 \
    --ports=30000:30000 \
    --ports=30001:30001 \
    --ports=30002:30002 \
    --ports=30003:30003 \
    --ports=30004:30004 \
    --ports=30005:30005 \
    --ports=30006:30006 \
    --ports=31935:31935 \
    --ports=32169:32169
else
  echo "Minikube already exists. Starting existing profile..."
  minikube start
fi

echo
echo "== Checking Minikube published ports =="

if ! docker ps --format '{{.Names}} {{.Ports}}' | grep '^minikube ' | grep -q '0.0.0.0:80->80/tcp'; then
  echo "WARNING: Minikube container does not publish host port 80."
  echo "Android access through http://<LAN-IP> may not work."
  echo
  echo "If this Minikube profile was created without --ports=80:80,"
  echo "recreate it manually:"
  echo
  echo "  minikube delete"
  echo "  ./scripts/local-k8s-start.sh"
  echo
fi

echo
echo "== Enabling ingress =="
minikube addons enable ingress

echo
echo "== Waiting for ingress-nginx controller =="
kubectl rollout status deployment/ingress-nginx-controller \
  -n ingress-nginx \
  --timeout=180s

kubectl wait \
  --namespace ingress-nginx \
  --for=condition=Ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=180s

echo
echo "== Checking ingress admission webhook =="
kubectl get svc ingress-nginx-controller-admission -n ingress-nginx >/dev/null

echo
echo "== Building local images inside Minikube Docker =="
eval "$(minikube docker-env)"

cd "$PROJECT_DIR"

docker build \
  -t learning-app-backend:local \
  -f app/backend/Dockerfile \
  .

docker build \
  -t learning-app-ingest:local \
  app/backend/ingest

cd "$FRONTEND_DIR"

docker build \
  -t learning-app-frontend:local \
  .

echo
echo "== Applying Kubernetes manifests =="
cd "$PROJECT_DIR"

kubectl apply -R -f deploy/k8s/base/

echo
echo "== Restarting deployments =="
kubectl rollout restart deployment || true

echo
echo "== Waiting for key deployments =="
kubectl rollout status deployment/identity-service --timeout=180s
kubectl rollout status deployment/web --timeout=180s
kubectl rollout status deployment/video-api --timeout=180s
kubectl rollout status deployment/upload-service --timeout=180s
kubectl rollout status deployment/live-api --timeout=180s
kubectl rollout status deployment/ingest --timeout=180s
kubectl rollout status deployment/origin --timeout=180s
kubectl rollout status deployment/frontend --timeout=180s

echo
echo "== Waiting for key statefulsets =="
kubectl rollout status statefulset/postgres-master --timeout=180s
kubectl rollout status statefulset/postgres-replica --timeout=180s
kubectl rollout status statefulset/rabbitmq --timeout=180s

echo
echo "== Final status =="
kubectl get pods
kubectl get svc
kubectl get ingress -o wide

echo
echo "== Access info =="
MINIKUBE_IP="$(minikube ip)"
LAN_IPS="$(hostname -I)"

echo "Minikube IP: ${MINIKUBE_IP}"
echo "LAN IPs:     ${LAN_IPS}"
echo
echo "NodePort URLs:"
echo "  Web/API:     http://${MINIKUBE_IP}:30000"
echo "  Frontend:    http://${MINIKUBE_IP}:30001"
echo "  Identity:    http://${MINIKUBE_IP}:30002"
echo "  Upload API:  http://${MINIKUBE_IP}:30003"
echo "  Video API:   http://${MINIKUBE_IP}:30004"
echo "  Live API:    http://${MINIKUBE_IP}:30005"
echo "  Origin:      http://${MINIKUBE_IP}:30006"
echo "  Grafana:     http://${MINIKUBE_IP}:30300"
echo "  Prometheus:  http://${MINIKUBE_IP}:30090"
echo
echo "Ingress/LAN URLs:"
echo "  Docs:        http://192.168.1.12/docs"
echo "  Videos API:  http://192.168.1.12/api/v1/videos"
echo "  Frontend:    http://192.168.1.12/"
echo
echo "Done."