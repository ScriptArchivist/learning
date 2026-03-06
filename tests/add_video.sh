#!/usr/bin/env bash
set -euo pipefail

# ---------------- CONFIG ----------------
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ci.yml}"

# upload flow / legacy web API
BASE="${BASE:-http://localhost:8000/api/v1}"

# status/read API
STATUS_BASE="${STATUS_BASE:-http://localhost:8003/api/v1}"

FILE="${FILE:-/home/vadim/Downloads/video5204062485010747752.mp4}"

# docker-compose service names
WEB_SVC="${WEB_SVC:-web}"
OUTBOX_SVC="${OUTBOX_SVC:-outbox-publisher}"
WORKER_SVC="${WORKER_SVC:-processing-worker}"
RABBIT_SVC="${RABBIT_SVC:-rabbitmq}"

LOG_DIR="${LOG_DIR:-./logs}"
LOG_SINCE_DEFAULT="${LOG_SINCE_DEFAULT:-15m}"
ATTEMPTS="${ATTEMPTS:-120}"
SLEEP="${SLEEP:-1}"

# при ожидании статуса читаем из master
CONSISTENT_QUERY="${CONSISTENT_QUERY:-?consistent=1}"

# JWT config
JWT_USER_ID="${JWT_USER_ID:-1}"
JWT_EXPIRES_MINUTES="${JWT_EXPIRES_MINUTES:-120}"
JWT_ISSUER="${JWT_ISSUER:-identity-service}"
JWT_AUDIENCE="${JWT_AUDIENCE:-video-platform}"

# ---------------- HELPERS ----------------
ts_now() { date +"%Y%m%d_%H%M%S"; }

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

check_api_error() {
  local body="$1"
  local code
  code="$(echo "$body" | jq -r '.error.code // empty' 2>/dev/null || true)"
  if [[ -n "$code" ]]; then
    echo "❌ API returned error:"
    echo "$body" | jq .
    exit 1
  fi
}

# ============ LOG COLLECTION ============
collect_logs() {
  local stage="$1"
  local rid="${2:-}"
  local vid="${3:-}"
  local since="${4:-$LOG_SINCE_DEFAULT}"
  local out_dir="${5:-$LOG_DIR}"

  mkdir -p "$out_dir"

  local ts prefix
  ts="$(ts_now)"
  prefix="${out_dir}/rid_${rid:-none}_vid_${vid:-none}_${ts}_${stage}"

  echo
  echo "==== COLLECT LOGS (${stage}) since ${since} RID=${rid:-none} VIDEO_ID=${vid:-none} ===="
  echo "Output prefix: ${prefix}"
  echo

  {
    echo "RID=${rid:-}"
    echo "VIDEO_ID=${vid:-}"
    echo "STAGE=${stage}"
    echo "SINCE=${since}"
    echo

    echo "===== WEB (${WEB_SVC}) ====="
    dc logs --since "${since}" "${WEB_SVC}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|/upload/complete|/videos/${vid}\b|status=|upload/prepare|upload/complete" || true
    echo

    echo "===== OUTBOX (${OUTBOX_SVC}) ====="
    dc logs --since "${since}" "${OUTBOX_SVC}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|event_type=video\.process|published|outbox|video\.process" || true
    echo

    echo "===== WORKER (${WORKER_SVC}) ====="
    dc logs --since "${since}" "${WORKER_SVC}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|start video_id=${vid}|done video_id=${vid}|ffmpeg|ffprobe|processing" || true
    echo

    echo "===== RABBITMQ (${RABBIT_SVC}) ====="
    dc logs --since "${since}" "${RABBIT_SVC}" 2>/dev/null \
      | egrep "${rid}|x-request-id|x-trace-id|video\.process" || true
    echo
  } > "${prefix}_TRACE.txt"

  dc logs --since "${since}" "${WEB_SVC}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}|upload/prepare|upload/complete" > "${prefix}_web.log" || true

  dc logs --since "${since}" "${OUTBOX_SVC}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}|video\.process|published|outbox" > "${prefix}_outbox.log" || true

  dc logs --since "${since}" "${WORKER_SVC}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}|start video_id=${vid}|done video_id=${vid}|ffmpeg|ffprobe|processing" > "${prefix}_worker.log" || true

  dc logs --since "${since}" "${RABBIT_SVC}" 2>/dev/null \
    | egrep "${rid}|x-request-id|x-trace-id|video\.process" > "${prefix}_rabbitmq.log" || true

  echo "Saved:"
  echo "  ${prefix}_TRACE.txt"
  echo "  ${prefix}_web.log"
  echo "  ${prefix}_outbox.log"
  echo "  ${prefix}_worker.log"
  echo "  ${prefix}_rabbitmq.log"
  echo "==============================================="
}

# ---------------- PRE-FLIGHT ----------------
need_cmd curl
need_cmd jq
need_cmd stat
need_cmd docker
need_cmd docker-compose
need_cmd python3

if [[ ! -f "$FILE" ]]; then
  echo "❌ File not found: $FILE"
  exit 1
fi

FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

CLIENT_UPLOAD_ID="$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"

TOKEN="$(generate_token)"
AUTH_HEADER="Authorization: Bearer $TOKEN"

mkdir -p "$LOG_DIR"
echo "$TOKEN" > "${LOG_DIR}/last_jwt.txt"
chmod 600 "${LOG_DIR}/last_jwt.txt" || true

echo "Using JWT: $TOKEN"
echo "JWT saved to: ${LOG_DIR}/last_jwt.txt"
echo "JWT_USER_ID=$JWT_USER_ID"
echo "JWT_ISSUER=$JWT_ISSUER"
echo "JWT_AUDIENCE=$JWT_AUDIENCE"
echo "CLIENT_UPLOAD_ID=$CLIENT_UPLOAD_ID"
echo "FILE=$FILE"
echo "FILENAME=$FILENAME"
echo "FILESIZE=$FILESIZE"
echo "BASE=$BASE"
echo "STATUS_BASE=$STATUS_BASE"

# ---------------- 1) PREPARE ----------------
echo
echo "1) prepare..."
RESP="$(curl -sS -X POST "$BASE/videos/upload/prepare" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"test video\",\"filename\":\"$FILENAME\",\"file_size\":$FILESIZE,\"client_upload_id\":\"$CLIENT_UPLOAD_ID\"}")"

echo "$RESP" | jq . || echo "$RESP"
check_api_error "$RESP"

VIDEO_ID="$(echo "$RESP" | jq -r '.video_id // .id')"
UPLOAD_ID="$(echo "$RESP" | jq -r '.upload_id')"
UPLOAD_URL="$(echo "$RESP" | jq -r '.upload_url')"
OBJECT_KEY="$(echo "$RESP" | jq -r '.object_key // empty')"

test -n "$VIDEO_ID" && test "$VIDEO_ID" != "null"
test -n "$UPLOAD_ID" && test "$UPLOAD_ID" != "null"
test -n "$UPLOAD_URL" && test "$UPLOAD_URL" != "null"

if [[ "$UPLOAD_URL" == /* ]]; then
  UPLOAD_URL="http://localhost:8000$UPLOAD_URL"
fi

echo "VIDEO_ID=$VIDEO_ID"
echo "UPLOAD_ID=$UPLOAD_ID"
echo "UPLOAD_URL=$UPLOAD_URL"
[[ -n "$OBJECT_KEY" ]] && echo "OBJECT_KEY=$OBJECT_KEY"

# ---------------- 2) DIRECT UPLOAD ----------------
echo
echo "2) upload direct..."
UPLOAD_RESP="$(curl -sS -X POST "$UPLOAD_URL" \
  -H "$AUTH_HEADER" \
  -F "file=@$FILE")"

echo "$UPLOAD_RESP" | jq . || echo "$UPLOAD_RESP"

# local storage md5
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

# ---------------- 3) COMPLETE + CAPTURE RID/TID ----------------
echo
echo "3) complete (capture RID/TID)..."
COMPLETE_RAW="$(curl -sS -i -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
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

collect_logs "after_complete" "${RID:-}" "$VIDEO_ID" "$LOG_SINCE_DEFAULT" "$LOG_DIR"

# ---------------- 3.1) COMPLETE AGAIN (IDEMPOTENCY) ----------------
echo
echo "3.1) complete again (idempotency check)..."
COMPLETE_2="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"
echo "$COMPLETE_2" | jq . || echo "$COMPLETE_2"

# ---------------- 4) WAIT READY ----------------
echo
echo "4) wait READY..."
for i in $(seq 1 "$ATTEMPTS"); do
  INFO="$(curl -sS -X GET "${STATUS_BASE}/videos/${VIDEO_ID}${CONSISTENT_QUERY}" -H "$AUTH_HEADER")"
  STATUS="$(echo "$INFO" | jq -r '.status // empty' 2>/dev/null || true)"

  if [[ -z "$STATUS" ]]; then
    echo "  [$i/$ATTEMPTS] non-json response, retry..."
    sleep "$SLEEP"
    continue
  fi

  if [[ "$STATUS" == "ready" ]]; then
    echo "✅ READY"
    break
  fi

  echo "  [$i/$ATTEMPTS] status=$STATUS"
  sleep "$SLEEP"
done

INFO="$(curl -sS -X GET "${STATUS_BASE}/videos/${VIDEO_ID}${CONSISTENT_QUERY}" -H "$AUTH_HEADER")"
STATUS="$(echo "$INFO" | jq -r '.status // empty')"

if [[ "$STATUS" != "ready" ]]; then
  echo "❌ Not READY after wait. Last status=$STATUS"
  echo "$INFO" | jq . || echo "$INFO"
  collect_logs "on_fail" "${RID:-}" "$VIDEO_ID" "30m" "$LOG_DIR"
  exit 1
fi

collect_logs "after_ready" "${RID:-}" "$VIDEO_ID" "$LOG_SINCE_DEFAULT" "$LOG_DIR"

HLS_URL="$(echo "$INFO" | jq -r '.hls_url // empty')"

echo
echo "==== LINKS (AUTH) ===="
echo "watch:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/watch"
echo "json:       ${STATUS_BASE}/videos/${VIDEO_ID}${CONSISTENT_QUERY}"
echo "mp4:        http://localhost:8000/api/v1/videos/${VIDEO_ID}/file"
echo "thumb:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/thumbnail"
echo "hls:        ${HLS_URL:-http://localhost:8000/api/v1/videos/${VIDEO_ID}/hls/master.m3u8}"
echo

# ---------------- 5) SHARE ----------------
echo "5) create share link..."
SHARE_RESP="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/share" -H "$AUTH_HEADER")"
echo "$SHARE_RESP" | jq . || echo "$SHARE_RESP"

SHARE_URL="$(echo "$SHARE_RESP" | jq -r '.share_url // empty')"
SHARE_TOKEN="$(echo "$SHARE_URL" | sed -E 's#.*/shared/##')"

if [[ -n "$SHARE_TOKEN" && "$SHARE_TOKEN" != "null" ]]; then
  echo
  echo "==== LINKS (SHARED) ===="
  echo "shared watch:  http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/watch"
  echo "shared json:   http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}"
  echo "shared mp4:    http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/file"
  echo "shared thumb:  http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/thumbnail"
  echo "shared hls:    http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/hls/master.m3u8"
  echo
else
  echo "ℹ️ Share URL/token not returned"
fi

echo "✅ Upload smoke test finished"