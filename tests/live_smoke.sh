#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ci.yml}"
WEB_SVC="${WEB_SVC:-web}"

API_URL="${API_URL:-http://localhost:8004/live/sessions}"

JWT_USER_ID="${JWT_USER_ID:-1}"
JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-120}"
JWT_ISSUER="${JWT_ISSUER:-identity-service}"
JWT_AUDIENCE="${JWT_AUDIENCE:-video-platform}"

FFMPEG_VIDEO_INPUT="${FFMPEG_VIDEO_INPUT:-testsrc=size=1280x720:rate=30}"
FFMPEG_AUDIO_INPUT="${FFMPEG_AUDIO_INPUT:-sine=frequency=1000:sample_rate=44100}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ Required command not found: $1"
    exit 1
  }
}

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

need_cmd curl
need_cmd python3
need_cmd ffmpeg
need_cmd docker-compose

TOKEN="$(generate_token)"
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "Using API_URL=$API_URL"
echo "JWT_USER_ID=$JWT_USER_ID"
echo "JWT_ISSUER=$JWT_ISSUER"
echo "JWT_AUDIENCE=$JWT_AUDIENCE"

echo "Creating live session..."
RESP="$(curl -sS -X POST "$API_URL" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"ttl_seconds":3600}')"

echo "$RESP"

SESSION_ID="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["id"])' "$RESP")"
STREAM_KEY="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$RESP")"
RTMP_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["rtmp_url"])' "$RESP")"
HLS_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["hls_url"])' "$RESP")"

echo "SESSION_ID=$SESSION_ID"
echo "STREAM_KEY=$STREAM_KEY"
echo "RTMP_URL=$RTMP_URL"
echo "HLS_URL=$HLS_URL"

LOG="/tmp/push_${STREAM_KEY}.log"

echo "Starting RTMP push..."
ffmpeg -re \
  -f lavfi -i "$FFMPEG_VIDEO_INPUT" \
  -f lavfi -i "$FFMPEG_AUDIO_INPUT" \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -preset veryfast \
  -g 48 \
  -c:a aac \
  -ar 44100 \
  -f flv \
  "$RTMP_URL" > "$LOG" 2>&1 &
PUSH_PID=$!

cleanup() {
  kill "$PUSH_PID" >/dev/null 2>&1 || true
  curl -sS -X DELETE "$API_URL/$SESSION_ID" -H "$AUTH_HEADER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Waiting for HLS..."
ok=0
for i in $(seq 1 60); do
  code="$(curl -s -o "/tmp/master_${STREAM_KEY}.m3u8" -w '%{http_code}' "$HLS_URL" || true)"
  if [[ "$code" == "200" ]] && [[ -s "/tmp/master_${STREAM_KEY}.m3u8" ]] && grep -q '^#EXTINF' "/tmp/master_${STREAM_KEY}.m3u8"; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "$ok" != "1" ]]; then
  echo "ERROR: HLS not ready"
  echo "---- ffmpeg push log ----"
  tail -n 80 "$LOG" || true
  exit 1
fi

echo "HLS playlist detected"

echo "Stopping push..."
kill "$PUSH_PID" >/dev/null 2>&1 || true
sleep 2

echo "Stopping live session..."
curl -sS -X DELETE "$API_URL/$SESSION_ID" -H "$AUTH_HEADER" >/dev/null

echo "SUCCESS: live smoke test passed"