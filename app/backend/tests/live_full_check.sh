#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ci.yml}"
WEB_SVC="${WEB_SVC:-web}"
LIVE_API_BASE="${LIVE_API_BASE:-http://localhost:8004}"
ORIGIN_BASE="${ORIGIN_BASE:-http://localhost:8080}"
INGEST_HEALTH_URL="${INGEST_HEALTH_URL:-http://localhost:8081/healthz}"

JWT_USER_ID="${JWT_USER_ID:-1}"
JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-120}"
JWT_ISSUER="${JWT_ISSUER:-identity-service}"
JWT_AUDIENCE="${JWT_AUDIENCE:-video-platform}"

LOG_DIR="${LOG_DIR:-./live_logs}"
mkdir -p "$LOG_DIR"

dc() {
  docker-compose -f "$COMPOSE_FILE" "$@"
}

generate_token() {
  dc exec -T "$WEB_SVC" python3 - <<PY | tail -n 1 | tr -d '\r'
import base64
import hashlib
import hmac
import json
import time
from src.config import settings

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def sign_hs256(message: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()

user_id = int("${JWT_USER_ID}")
expires_minutes = int("${JWT_EXPIRES_MINUTES}")
issuer = "${JWT_ISSUER}"
audience = "${JWT_AUDIENCE}"

header = {"alg": "HS256", "typ": "JWT"}
now = int(time.time())
payload = {
    "sub": str(user_id),
    "iat": now,
    "exp": now + int(expires_minutes * 60),
    "iss": issuer,
    "aud": audience,
    "role": "user",
}

header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
sig_b64 = b64url(sign_hs256(signing_input, settings.secret_key))

print(f"{header_b64}.{payload_b64}.{sig_b64}")
PY
}

echo "=============================="
echo "LIVE SYSTEM FULL CHECK"
echo "=============================="

echo
echo "1️⃣ checking services..."

curl -fsS "${LIVE_API_BASE}/health" >/dev/null && echo "live-api OK"
curl -fsS "${INGEST_HEALTH_URL}" >/dev/null && echo "ingest OK"
curl -fsS "${ORIGIN_BASE}/healthz" >/dev/null && echo "origin OK"

echo
echo "2️⃣ generating JWT..."
TOKEN="$(generate_token)"
AUTH_HEADER="Authorization: Bearer $TOKEN"
echo "JWT generated"

echo
echo "3️⃣ creating live session..."

RESP="$(curl -fsS -X POST "${LIVE_API_BASE}/live/sessions" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: live-full-check-001" \
  -d '{"ttl_seconds":3600}')"

echo "$RESP" | tee "${LOG_DIR}/create_live_response.json"

SESSION_ID="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["id"])' "$RESP")"
STREAM_KEY="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$RESP")"
RTMP_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["rtmp_url"])' "$RESP")"
HLS_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["hls_url"])' "$RESP")"

echo
echo "SESSION_ID=$SESSION_ID"
echo "STREAM_KEY=$STREAM_KEY"
echo "RTMP_URL=$RTMP_URL"
echo "HLS_URL=$HLS_URL"

echo
echo "4️⃣ checking live session before publish..."
curl -fsS "${LIVE_API_BASE}/live/sessions/${STREAM_KEY}" \
  -H "$AUTH_HEADER" | tee "${LOG_DIR}/session_before_publish.json"

echo
echo "5️⃣ starting test stream..."

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
  "$RTMP_URL" > "${LOG_DIR}/ffmpeg_publish.log" 2>&1 &

PID=$!

cleanup() {
  kill "$PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo
echo "6️⃣ waiting for HLS..."

HLS_READY=0
for i in $(seq 1 30); do
  STATUS="$(curl -s -o /dev/null -w "%{http_code}" "$HLS_URL" || true)"
  echo "attempt=$i status=$STATUS" | tee -a "${LOG_DIR}/hls_wait.log"
  if [ "$STATUS" = "200" ]; then
    curl -fsS "$HLS_URL" > "${LOG_DIR}/master.m3u8"
    if grep -q '^#EXTM3U' "${LOG_DIR}/master.m3u8"; then
      HLS_READY=1
      echo "HLS READY"
      break
    fi
  fi
  sleep 1
done

echo
echo "7️⃣ playlist result..."
if [ "$HLS_READY" = "1" ]; then
  cat "${LOG_DIR}/master.m3u8"
else
  echo "HLS NOT READY"
fi

echo
echo "8️⃣ ingest logs"
dc logs --tail=100 ingest | tee "${LOG_DIR}/ingest.log"

echo
echo "9️⃣ origin logs"
dc logs --tail=50 origin | tee "${LOG_DIR}/origin.log"

echo
echo "🔟 live-api logs"
dc logs --tail=100 live-api | tee "${LOG_DIR}/live-api.log"

echo
echo "1️⃣1️⃣ files in ingest volume"
dc exec -T ingest sh -lc "find /app/uploads/live -maxdepth 3 -type f | sort" \
  | tee "${LOG_DIR}/ingest_files.log" || true

echo
echo "1️⃣2️⃣ files in origin volume"
dc exec -T origin sh -lc "find /app/uploads/live -maxdepth 3 -type f | sort" \
  | tee "${LOG_DIR}/origin_files.log" || true

echo
echo "1️⃣3️⃣ stopping test stream"
kill "$PID" >/dev/null 2>&1 || true
sleep 2

echo
echo "1️⃣4️⃣ stopping live session..."
curl -i -fsS -X DELETE "${LIVE_API_BASE}/live/sessions/${SESSION_ID}" \
  -H "$AUTH_HEADER" | tee "${LOG_DIR}/stop_response.txt"

echo
echo "1️⃣5️⃣ check HLS after stop"
curl -i -sS "$HLS_URL" | tee "${LOG_DIR}/hls_after_stop.txt" || true

echo
echo "=============================="
echo "CHECK COMPLETE"
echo "=============================="
echo "Logs saved to: ${LOG_DIR}"