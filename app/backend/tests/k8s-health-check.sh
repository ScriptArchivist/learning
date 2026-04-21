#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-default}"

BASE_URL="${BASE_URL:-http://192.168.49.2}"
WEB_URL="${WEB_URL:-$BASE_URL:30000/docs}"
FRONTEND_URL="${FRONTEND_URL:-$BASE_URL:30001/login}"
UPLOAD_URL="${UPLOAD_URL:-$BASE_URL:30002/docs}"
VIDEO_API_URL="${VIDEO_API_URL:-$BASE_URL:30003/docs}"
LIVE_API_URL="${LIVE_API_URL:-$BASE_URL:30004/docs}"
GRAFANA_URL="${GRAFANA_URL:-$BASE_URL:30300}"

red()    { printf '\033[31m%s\033[0m\n' "$1"; }
green()  { printf '\033[32m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
blue()   { printf '\033[34m%s\033[0m\n' "$1"; }

section() {
  echo
  blue "========== $1 =========="
}

ok()   { green "OK: $1"; }
warn() { yellow "WARN: $1"; }
fail() { red "FAIL: $1"; }

check_url() {
  local name="$1"
  local url="$2"

  if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
    ok "$name -> $url"
  else
    fail "$name -> $url"
  fi
}

section "1. Pods"
kubectl get pods -n "$NS"

NOT_RUNNING="$(kubectl get pods -n "$NS" --no-headers | awk '$3 != "Running" && $3 != "Completed" {print $1"  "$3}')"
if [[ -z "$NOT_RUNNING" ]]; then
  ok "Все pod'ы в состояниях Running/Completed"
else
  warn "Есть pod'ы не в Running/Completed:"
  echo "$NOT_RUNNING"
fi

section "2. PVC"
kubectl get pvc -n "$NS" || true

PVC_BAD="$(kubectl get pvc -n "$NS" --no-headers 2>/dev/null | awk '$2 != "Bound" {print $1"  "$2}')"
if [[ -z "${PVC_BAD:-}" ]]; then
  ok "Все PVC в Bound"
else
  warn "Есть PVC не в Bound:"
  echo "$PVC_BAD"
fi

section "3. Critical infra"
kubectl get pods -n "$NS" | grep -E "postgres|rabbitmq|redis" || true

for name in postgres-master-0 postgres-replica-0 rabbitmq-0; do
  if kubectl get pod "$name" -n "$NS" >/dev/null 2>&1; then
    phase="$(kubectl get pod "$name" -n "$NS" -o jsonpath='{.status.phase}')"
    if [[ "$phase" == "Running" ]]; then
      ok "$name is Running"
    else
      warn "$name phase=$phase"
    fi
  fi
done

section "4. Restarts"
kubectl get pods -n "$NS" --no-headers | awk '{print $1, $4}' | while read -r pod restarts; do
  if [[ "${restarts:-0}" != "0" ]]; then
    warn "$pod restarts=$restarts"
  fi
done

section "5. Jobs"
for job in migrate dlq-replayer; do
  if kubectl get job "$job" -n "$NS" >/dev/null 2>&1; then
    succeeded="$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.succeeded}')"
    failed="$(kubectl get job "$job" -n "$NS" -o jsonpath='{.status.failed}')"
    succeeded="${succeeded:-0}"
    failed="${failed:-0}"

    if [[ "$succeeded" != "0" ]]; then
      ok "job/$job completed"
    elif [[ "$failed" != "0" ]]; then
      fail "job/$job failed"
    else
      warn "job/$job still in progress"
    fi
  else
    warn "job/$job not found"
  fi
done

section "6. HTTP endpoints"
check_url "Web API" "$WEB_URL"
check_url "Frontend" "$FRONTEND_URL"
check_url "Upload Service" "$UPLOAD_URL"
check_url "Video API" "$VIDEO_API_URL"
check_url "Live API" "$LIVE_API_URL"
check_url "Grafana" "$GRAFANA_URL/login"

section "7. Key logs tail"
for target in deployment/processing-worker deployment/video-events-consumer deployment/outbox-publisher; do
  echo
  blue "--- $target ---"
  kubectl logs -n "$NS" "$target" --tail=20 2>/dev/null || warn "Не удалось получить логи $target"
done

section "8. Grafana dashboards"
if curl -fsS --max-time 5 -u admin:admin http://127.0.0.1:3000/api/search >/dev/null 2>&1; then
  DASHES="$(curl -fsS -u admin:admin http://127.0.0.1:3000/api/search)"
  echo "$DASHES" | grep -q 'video-platform-k8s-overview' && ok "Overview dashboard найден" || fail "Overview dashboard не найден"
  echo "$DASHES" | grep -q 'video-platform-k8s-api' && ok "API dashboard найден" || fail "API dashboard не найден"
  echo "$DASHES" | grep -q 'video-platform-k8s-pipeline' && ok "Pipeline dashboard найден" || fail "Pipeline dashboard не найден"
  echo "$DASHES" | grep -q 'video-platform-k8s-slo' && ok "SLO dashboard найден" || fail "SLO dashboard не найден"
else
  warn "Grafana API на 127.0.0.1:3000 недоступен. Если нужно, сначала выполни:"
  echo "kubectl port-forward svc/grafana 3000:3000"
fi

section "9. Quick links"
echo "Web API:        $WEB_URL"
echo "Frontend:       $FRONTEND_URL"
echo "Upload Service: $UPLOAD_URL"
echo "Video API:      $VIDEO_API_URL"
echo "Live API:       $LIVE_API_URL"
echo "Grafana:        $GRAFANA_URL"