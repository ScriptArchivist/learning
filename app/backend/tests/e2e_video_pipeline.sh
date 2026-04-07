#!/usr/bin/env bash
set -euo pipefail

# =========================================================
# E2E smoke test:
# upload -> complete -> outbox -> worker -> READY
# -> video-api read
# -> video-api consistent read
# -> playback
# -> share
# -> HLS availability
# =========================================================

# ---------------- CONFIG ----------------
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ci.yml}"

WEB_BASE="${WEB_BASE:-http://localhost:8000/api/v1}"
VIDEO_API_BASE="${VIDEO_API_BASE:-http://localhost:8003/api/v1}"
ORIGIN_BASE="${ORIGIN_BASE:-http://localhost:8080}"

FILE="${FILE:-/home/vadim/Downloads/video5204062485010747752.mp4}"

WEB_SVC="${WEB_SVC:-web}"
VIDEO_API_SVC="${VIDEO_API_SVC:-video-api}"
OUTBOX_SVC="${OUTBOX_SVC:-outbox-publisher}"
WORKER_SVC="${WORKER_SVC:-processing-worker}"
RABBIT_SVC="${RABBIT_SVC:-rabbitmq}"
ORIGIN_SVC="${ORIGIN_SVC:-origin}"

JWT_USER_ID="${JWT_USER_ID:-1}"
JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-120}"
JWT_ISSUER="${JWT_ISSUER:-identity-service}"
JWT_AUDIENCE="${JWT_AUDIENCE:-video-platform}"

ATTEMPTS="${ATTEMPTS:-180}"
SLEEP="${SLEEP:-2}"
LOG_SINCE="${LOG_SINCE:-30m}"
LOG_DIR="${LOG_DIR:-./logs}"

# ---------------- HELPERS ----------------
need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ Required command not found: $1"
    exit 1
  }
}

dc() {
  docker-compose -f "$COMPOSE_FILE" "$@"
}

ts_now() {
  date +"%Y%m%d_%H%M%S"
}

fail() {
  echo
  echo "❌ E2E FAILED: $*"
  echo
  collect_logs "on_fail" "${RID:-}" "${VIDEO_ID:-}" "$LOG_SINCE"
  exit 1
}

json_field() {
  local json="$1"
  local expr="$2"
  echo "$json" | jq -r "$expr"
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

collect_logs() {
  local stage="$1"
  local rid="${2:-}"
  local vid="${3:-}"
  local since="${4:-30m}"

  mkdir -p "$LOG_DIR"

  local ts prefix
  ts="$(ts_now)"
  prefix="${LOG_DIR}/e2e_${stage}_rid_${rid:-none}_vid_${vid:-none}_${ts}"

  {
    echo "STAGE=${stage}"
    echo "RID=${rid:-}"
    echo "VIDEO_ID=${vid:-}"
    echo "SINCE=${since}"
    echo

    echo "===== ${WEB_SVC} ====="
    dc logs --since "$since" "$WEB_SVC" 2>/dev/null || true
    echo

    echo "===== ${VIDEO_API_SVC} ====="
    dc logs --since "$since" "$VIDEO_API_SVC" 2>/dev/null || true
    echo

    echo "===== ${OUTBOX_SVC} ====="
    dc logs --since "$since" "$OUTBOX_SVC" 2>/dev/null || true
    echo

    echo "===== ${WORKER_SVC} ====="
    dc logs --since "$since" "$WORKER_SVC" 2>/dev/null || true
    echo

    echo "===== ${RABBIT_SVC} ====="
    dc logs --since "$since" "$RABBIT_SVC" 2>/dev/null || true
    echo

    echo "===== ${ORIGIN_SVC} ====="
    dc logs --since "$since" "$ORIGIN_SVC" 2>/dev/null || true
    echo
  } > "${prefix}_ALL.log"

  echo "📦 Logs saved: ${prefix}_ALL.log"
}

api_error_check() {
  local body="$1"
  local code
  code="$(echo "$body" | jq -r '.error.code // empty' 2>/dev/null || true)"
  if [[ -n "$code" ]]; then
    echo "$body" | jq .
    fail "API returned error code=${code}"
  fi
}

http_ok() {
  local url="$1"
  local auth="${2:-}"
  local code

  if [[ -n "$auth" ]]; then
    code="$(curl -sS -o /dev/null -w '%{http_code}' -H "$auth" "$url")"
  else
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url")"
  fi

  [[ "$code" == "200" ]]
}

# ---------------- PRE-FLIGHT ----------------
need_cmd curl
need_cmd jq
need_cmd stat
need_cmd docker-compose
need_cmd python3

[[ -f "$FILE" ]] || fail "File not found: $FILE"

mkdir -p "$LOG_DIR"

FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

CLIENT_UPLOAD_ID="$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"

TOKEN="$(generate_token)"
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "$TOKEN" > "${LOG_DIR}/last_jwt.txt"
chmod 600 "${LOG_DIR}/last_jwt.txt" || true

echo "========================================================="
echo "E2E video pipeline smoke test"
echo "WEB_BASE=$WEB_BASE"
echo "VIDEO_API_BASE=$VIDEO_API_BASE"
echo "ORIGIN_BASE=$ORIGIN_BASE"
echo "FILE=$FILE"
echo "FILENAME=$FILENAME"
echo "FILESIZE=$FILESIZE"
echo "JWT_USER_ID=$JWT_USER_ID"
echo "JWT_ISSUER=$JWT_ISSUER"
echo "JWT_AUDIENCE=$JWT_AUDIENCE"
echo "CLIENT_UPLOAD_ID=$CLIENT_UPLOAD_ID"
echo "========================================================="

# ---------------- 0) HEALTH ----------------
echo
echo "0) health checks..."
http_ok "http://localhost:8000/health" || fail "web /health failed"
http_ok "http://localhost:8003/health" || fail "video-api /health failed"
echo "✅ health ok"

# ---------------- 1) PREPARE ----------------
echo
echo "1) prepare..."
PREPARE_RESP="$(curl -sS -X POST "$WEB_BASE/videos/upload/prepare" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"e2e smoke video\",\"filename\":\"$FILENAME\",\"file_size\":$FILESIZE,\"client_upload_id\":\"$CLIENT_UPLOAD_ID\"}")"

echo "$PREPARE_RESP" | jq .
api_error_check "$PREPARE_RESP"

VIDEO_ID="$(json_field "$PREPARE_RESP" '.video_id // .id')"
UPLOAD_ID="$(json_field "$PREPARE_RESP" '.upload_id')"
UPLOAD_URL="$(json_field "$PREPARE_RESP" '.upload_url')"

[[ -n "$VIDEO_ID" && "$VIDEO_ID" != "null" ]] || fail "prepare: VIDEO_ID empty"
[[ -n "$UPLOAD_ID" && "$UPLOAD_ID" != "null" ]] || fail "prepare: UPLOAD_ID empty"
[[ -n "$UPLOAD_URL" && "$UPLOAD_URL" != "null" ]] || fail "prepare: UPLOAD_URL empty"

if [[ "$UPLOAD_URL" == /* ]]; then
  UPLOAD_URL="http://localhost:8000$UPLOAD_URL"
fi

echo "VIDEO_ID=$VIDEO_ID"
echo "UPLOAD_ID=$UPLOAD_ID"
echo "UPLOAD_URL=$UPLOAD_URL"

# ---------------- 2) DIRECT UPLOAD ----------------
echo
echo "2) direct upload..."
UPLOAD_RESP="$(curl -sS -X POST "$UPLOAD_URL" \
  -H "$AUTH_HEADER" \
  -F "file=@$FILE")"

echo "$UPLOAD_RESP" | jq . || echo "$UPLOAD_RESP"

ETAG="$(python3 - <<PY
import hashlib
p="$FILE"
h=hashlib.md5()
with open(p,"rb") as f:
    for chunk in iter(lambda: f.read(1024*1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"

# ---------------- 3) COMPLETE ----------------
echo
echo "3) complete..."
COMPLETE_RAW="$(curl -sS -i -X POST "$WEB_BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"

COMPLETE_HEADERS="$(echo "$COMPLETE_RAW" | tr -d '\r' | sed -n '1,/^$/p')"
COMPLETE_BODY="$(echo "$COMPLETE_RAW" | tr -d '\r' | sed -n '/^$/,$p' | tail -n +2)"

RID="$(echo "$COMPLETE_HEADERS" | awk -F': ' 'tolower($1)=="x-request-id"{print $2; exit}')"
TID="$(echo "$COMPLETE_HEADERS" | awk -F': ' 'tolower($1)=="x-trace-id"{print $2; exit}')"

echo "RID=${RID:-}"
echo "TID=${TID:-}"
echo "$COMPLETE_BODY" | jq . || echo "$COMPLETE_BODY"

# ---------------- 3.1) COMPLETE AGAIN ----------------
echo
echo "3.1) complete again (idempotency)..."
COMPLETE_2="$(curl -sS -X POST "$WEB_BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"
echo "$COMPLETE_2" | jq . || echo "$COMPLETE_2"

collect_logs "after_complete" "${RID:-}" "$VIDEO_ID" "15m"

# ---------------- 4) WAIT READY (CONSISTENT) ----------------
echo
echo "4) wait READY via video-api consistent read..."
READY_JSON=""
for i in $(seq 1 "$ATTEMPTS"); do
  READY_JSON="$(curl -sS -X GET "${VIDEO_API_BASE}/videos/${VIDEO_ID}?consistent=1" -H "$AUTH_HEADER" || true)"
  STATUS="$(echo "$READY_JSON" | jq -r '.status // empty' 2>/dev/null || true)"

  if [[ "$STATUS" == "ready" ]]; then
    echo "✅ READY"
    break
  fi

  if [[ -n "$STATUS" ]]; then
    echo "  [$i/$ATTEMPTS] status=$STATUS"
  else
    echo "  [$i/$ATTEMPTS] non-json or empty response"
  fi

  sleep "$SLEEP"
done

FINAL_JSON="$(curl -sS -X GET "${VIDEO_API_BASE}/videos/${VIDEO_ID}?consistent=1" -H "$AUTH_HEADER")"
FINAL_STATUS="$(echo "$FINAL_JSON" | jq -r '.status // empty')"

[[ "$FINAL_STATUS" == "ready" ]] || {
  echo "$FINAL_JSON" | jq . || echo "$FINAL_JSON"
  fail "video did not reach READY"
}

collect_logs "after_ready" "${RID:-}" "$VIDEO_ID" "15m"

# ---------------- 5) CHECK NORMAL READ + CONSISTENT READ ----------------
echo
echo "5) verify read endpoints..."
READ_REPLICA="$(curl -sS -X GET "${VIDEO_API_BASE}/videos/${VIDEO_ID}" -H "$AUTH_HEADER")"
READ_MASTER="$(curl -sS -X GET "${VIDEO_API_BASE}/videos/${VIDEO_ID}?consistent=1" -H "$AUTH_HEADER")"

echo "Replica read:"
echo "$READ_REPLICA" | jq .

echo "Master consistent read:"
echo "$READ_MASTER" | jq .

REPLICA_ID="$(echo "$READ_REPLICA" | jq -r '.id // empty')"
MASTER_ID="$(echo "$READ_MASTER" | jq -r '.id // empty')"

[[ "$REPLICA_ID" == "$VIDEO_ID" ]] || fail "replica read returned wrong id"
[[ "$MASTER_ID" == "$VIDEO_ID" ]] || fail "master consistent read returned wrong id"

# ---------------- 6) PLAYBACK ----------------
echo
echo "6) playback..."
PLAYBACK_JSON="$(curl -sS -X GET "${VIDEO_API_BASE}/videos/${VIDEO_ID}/playback?consistent=1" -H "$AUTH_HEADER")"
echo "$PLAYBACK_JSON" | jq .

HLS_READY="$(echo "$PLAYBACK_JSON" | jq -r '.hls_ready // empty')"
HLS_URL="$(echo "$PLAYBACK_JSON" | jq -r '.hls_url // empty')"

[[ "$HLS_READY" == "true" ]] || fail "playback.hls_ready != true"
[[ -n "$HLS_URL" && "$HLS_URL" != "null" ]] || fail "playback.hls_url empty"

# ---------------- 7) HLS AVAILABILITY ----------------
echo
echo "7) check HLS availability..."
echo "HLS_URL=$HLS_URL"

HLS_CODE="$(curl -sS -o /tmp/e2e_master.m3u8 -w '%{http_code}' "$HLS_URL")"
[[ "$HLS_CODE" == "200" ]] || fail "HLS master playlist not reachable, http=$HLS_CODE"

grep -q "#EXTM3U" /tmp/e2e_master.m3u8 || fail "HLS master playlist invalid"
echo "✅ HLS playlist reachable"

# ---------------- 8) SHARE ----------------
echo
echo "8) share..."
SHARE_JSON="$(curl -sS -X POST "$WEB_BASE/videos/${VIDEO_ID}/share" -H "$AUTH_HEADER")"
echo "$SHARE_JSON" | jq . || echo "$SHARE_JSON"

SHARE_URL="$(echo "$SHARE_JSON" | jq -r '.share_url // empty')"
if [[ -n "$SHARE_URL" && "$SHARE_URL" != "null" ]]; then
  echo "SHARE_URL=$SHARE_URL"
else
  echo "ℹ️ share_url not returned; skipping shared-url assertions"
fi

# ---------------- 9) FINAL SUMMARY ----------------
echo
echo "========================================================="
echo "✅ E2E PASSED"
echo "VIDEO_ID=$VIDEO_ID"
echo "RID=${RID:-}"
echo "TID=${TID:-}"
echo "HLS_URL=$HLS_URL"
echo "LOG_DIR=$LOG_DIR"
echo "========================================================="