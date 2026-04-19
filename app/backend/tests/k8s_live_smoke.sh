#!/usr/bin/env bash
set -euo pipefail

echo "🚀 K8S LIVE SMOKE TEST START"

MINIKUBE_IP="${MINIKUBE_IP:-$(minikube ip)}"

WEB_DEPLOY="${WEB_DEPLOY:-web}"
LIVE_API_BASE="${LIVE_API_BASE:-http://${MINIKUBE_IP}:30005}"
INGEST_HEALTH_URL="${INGEST_HEALTH_URL:-http://${MINIKUBE_IP}:32169/healthz}"
ORIGIN_HEALTH_URL="${ORIGIN_HEALTH_URL:-http://${MINIKUBE_IP}:30006/healthz}"

JWT_USER_ID="${JWT_USER_ID:-1}"
JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-120}"
JWT_ISSUER="${JWT_ISSUER:-identity-service}"
JWT_AUDIENCE="${JWT_AUDIENCE:-video-platform}"

IDEMPOTENCY_KEY="${IDEMPOTENCY_KEY:-k8s-live-smoke-001}"
TTL_SECONDS="${TTL_SECONDS:-3600}"
WAIT_ATTEMPTS="${WAIT_ATTEMPTS:-60}"
WAIT_SLEEP_SECONDS="${WAIT_SLEEP_SECONDS:-2}"

LOG_DIR="${LOG_DIR:-./live_logs_k8s}"
mkdir -p "$LOG_DIR"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ Required command not found: $1"
    exit 1
  }
}

need_cmd curl
need_cmd jq
need_cmd ffmpeg
need_cmd kubectl
need_cmd python3
need_cmd minikube

echo "📍 MINIKUBE_IP=$MINIKUBE_IP"
echo "📍 LIVE_API_BASE=$LIVE_API_BASE"
echo "📍 INGEST_HEALTH_URL=$INGEST_HEALTH_URL"
echo "📍 ORIGIN_HEALTH_URL=$ORIGIN_HEALTH_URL"

echo "1) Health checks..."
curl -fsS "$LIVE_API_BASE/health" >/dev/null && echo "✅ live-api OK"
curl -fsS "$INGEST_HEALTH_URL" >/dev/null && echo "✅ ingest OK"
curl -fsS "$ORIGIN_HEALTH_URL" >/dev/null && echo "✅ origin OK"

echo "2) Ensuring test user exists..."
kubectl exec postgres-master-0 -- env PGPASSWORD=postgres \
psql -U postgres -d app -c "
insert into users (id, username, email, hashed_password, is_active, role, storage_limit, used_storage)
values (${JWT_USER_ID}, 'vadim', 'vadim@example.com', 'debug', true, 'user', 10737418240, 0)
on conflict (id) do nothing;
" >/dev/null
echo "✅ user ready"

echo "3) Generating JWT..."
TOKEN="$(kubectl exec deploy/${WEB_DEPLOY} -- python3 -c '
import base64, hashlib, hmac, json, time
from src.config import settings

b64 = lambda d: base64.urlsafe_b64encode(d).decode().rstrip("=")
sign = lambda m, s: hmac.new(s.encode(), m, hashlib.sha256).digest()

user_id = "'"${JWT_USER_ID}"'"
expires_minutes = int("'"${JWT_EXPIRES_MINUTES}"'")
issuer = "'"${JWT_ISSUER}"'"
audience = "'"${JWT_AUDIENCE}"'"

now = int(time.time())
header = {"alg":"HS256","typ":"JWT"}
payload = {
    "sub": str(user_id),
    "iat": now,
    "exp": now + expires_minutes * 60,
    "iss": issuer,
    "aud": audience,
    "role": "user",
}

hb = b64(json.dumps(header, separators=(",", ":")).encode())
pb = b64(json.dumps(payload, separators=(",", ":")).encode())
si = f"{hb}.{pb}".encode()

print(f"{hb}.{pb}.{b64(sign(si, settings.secret_key))}")
')"

AUTH_HEADER="Authorization: Bearer $TOKEN"
[ -n "$TOKEN" ] || { echo "❌ TOKEN EMPTY"; exit 1; }
echo "✅ JWT ready"

echo "4) Creating live session..."
RESP="$(curl -fsS -X POST "${LIVE_API_BASE}/live/sessions" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: ${IDEMPOTENCY_KEY}" \
  -d "{\"ttl_seconds\":${TTL_SECONDS}}")"

echo "$RESP" | tee "${LOG_DIR}/create_live_response.json" | jq .

SESSION_ID="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["id"])' "$RESP")"
STREAM_KEY="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$RESP")"
RTMP_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["rtmp_url"])' "$RESP")"
HLS_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["hls_url"])' "$RESP")"

echo "✅ SESSION_ID=$SESSION_ID"
echo "✅ STREAM_KEY=$STREAM_KEY"
echo "✅ RTMP_URL=$RTMP_URL"
echo "✅ HLS_URL=$HLS_URL"

echo "5) Checking live session before publish..."
curl -fsS "${LIVE_API_BASE}/live/sessions/${STREAM_KEY}" \
  -H "$AUTH_HEADER" | tee "${LOG_DIR}/session_before_publish.json" | jq .

echo "6) Starting test RTMP stream..."
FFMPEG_LOG="${LOG_DIR}/ffmpeg_publish.log"

ffmpeg -re \
  -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=1000:sample_rate=44100 \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -preset veryfast \
  -g 48 \
  -c:a aac \
  -ar 44100 \
  -f flv \
  "$RTMP_URL" > "$FFMPEG_LOG" 2>&1 &

PUSH_PID=$!

cleanup() {
  kill "$PUSH_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "7) Waiting for HLS..."
HLS_READY=0

for i in $(seq 1 "$WAIT_ATTEMPTS"); do
  STATUS_CODE="$(curl -s -o /tmp/k8s_live_master.m3u8 -w "%{http_code}" "$HLS_URL" || true)"
  echo "attempt=$i status=$STATUS_CODE" | tee -a "${LOG_DIR}/hls_wait.log"

  if [ "$STATUS_CODE" = "200" ]; then
    if grep -q '^#EXTM3U' /tmp/k8s_live_master.m3u8; then
      HLS_READY=1
      cp /tmp/k8s_live_master.m3u8 "${LOG_DIR}/master.m3u8"
      echo "✅ HLS READY"
      break
    fi
  fi

  sleep "$WAIT_SLEEP_SECONDS"
done

echo "8) Playlist result..."
if [ "$HLS_READY" = "1" ]; then
  cat "${LOG_DIR}/master.m3u8"
else
  echo "❌ HLS NOT READY"
  echo "---- ffmpeg publish log ----"
  tail -n 80 "$FFMPEG_LOG" || true
  echo "---- ingest logs ----"
  kubectl logs deploy/ingest --tail=100 || true
  echo "---- origin logs ----"
  kubectl logs deploy/origin --tail=100 || true
  echo "---- live-api logs ----"
  kubectl logs deploy/live-api --tail=100 || true
  exit 1
fi

echo "9) Checking live session during publish..."
curl -fsS "${LIVE_API_BASE}/live/sessions/${STREAM_KEY}" \
  -H "$AUTH_HEADER" | tee "${LOG_DIR}/session_during_publish.json" | jq .

echo "10) Stopping test stream..."
kill "$PUSH_PID" >/dev/null 2>&1 || true
sleep 2

echo "11) Stopping live session..."
curl -i -fsS -X DELETE "${LIVE_API_BASE}/live/sessions/${SESSION_ID}" \
  -H "$AUTH_HEADER" | tee "${LOG_DIR}/stop_response.txt"

echo "12) HLS after stop (informational)..."
curl -i -sS "$HLS_URL" | tee "${LOG_DIR}/hls_after_stop.txt" || true

echo "13) Useful logs..."
kubectl logs deploy/ingest --tail=100 | tee "${LOG_DIR}/ingest.log" || true
kubectl logs deploy/origin --tail=50 | tee "${LOG_DIR}/origin.log" || true
kubectl logs deploy/live-api --tail=100 | tee "${LOG_DIR}/live-api.log" || true

echo "14) Files in ingest volume..."
kubectl exec deploy/ingest -- sh -lc "find /app/uploads/live -maxdepth 3 -type f | sort" \
  | tee "${LOG_DIR}/ingest_files.log" || true

echo "15) Files in origin volume..."
kubectl exec deploy/origin -- sh -lc "find /app/uploads/live -maxdepth 3 -type f | sort" \
  | tee "${LOG_DIR}/origin_files.log" || true

echo
echo "🎉 K8S LIVE SMOKE TEST PASSED"
echo "SESSION_ID=$SESSION_ID"
echo "STREAM_KEY=$STREAM_KEY"
echo "HLS_URL=$HLS_URL"
echo "LOG_DIR=$LOG_DIR"