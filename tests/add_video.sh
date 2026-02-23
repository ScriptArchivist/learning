#!/usr/bin/env bash
set -euo pipefail

# ---------------- CONFIG ----------------
BASE="${BASE:-http://localhost:8000/api/v1}"
FILE="${FILE:-/home/vadim/Downloads/video5204062485010747752.mp4}"

# docker container names (override if needed)
WEB_C="${WEB_C:-learning_app-web-1}"
OUTBOX_C="${OUTBOX_C:-learning_app-outbox-1}"
WORKER_C="${WORKER_C:-learning_app-worker-1}"
RABBIT_C="${RABBIT_C:-learning_app-rabbitmq-1}"

LOG_DIR="${LOG_DIR:-./logs}"
LOG_SINCE_DEFAULT="${LOG_SINCE_DEFAULT:-15m}"  # docker logs --since accepts 15m/30m/1h etc.
ATTEMPTS="${ATTEMPTS:-60}"
SLEEP="${SLEEP:-1}"

# ---------------- HELPERS ----------------
ts_now() { date +"%Y%m%d_%H%M%S"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "❌ Required command not found: $1"
    exit 1
  }
}

# ============ LOG COLLECTION ============
collect_logs() {
  local stage="$1"         # after_complete / after_ready / on_fail
  local rid="${2:-}"
  local vid="${3:-}"
  local since="${4:-$LOG_SINCE_DEFAULT}"
  local out_dir="${5:-$LOG_DIR}"

  if [[ -z "${rid}" ]]; then
    echo "collect_logs: RID is empty, skip"
    return 0
  fi

  mkdir -p "$out_dir"

  local ts prefix
  ts="$(ts_now)"
  prefix="${out_dir}/rid_${rid}_vid_${vid}_${ts}_${stage}"

  echo
  echo "==== COLLECT LOGS (${stage}) since ${since} RID=${rid} VIDEO_ID=${vid} ===="
  echo "Output prefix: ${prefix}"
  echo

  # Склейка
  {
    echo "RID=${rid}"
    echo "VIDEO_ID=${vid}"
    echo "STAGE=${stage}"
    echo "SINCE=${since}"
    echo

    echo "===== WEB (${WEB_C}) (rid=${rid} OR video_id=${vid}) ====="
    docker logs --since "${since}" "${WEB_C}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|/upload/complete|/videos/${vid}\b|status=" || true
    echo

    echo "===== OUTBOX (${OUTBOX_C}) (rid=${rid} OR video_id=${vid}) ====="
    docker logs --since "${since}" "${OUTBOX_C}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|event_type=video\.process|published|outbox" || true
    echo

    echo "===== WORKER (${WORKER_C}) (rid=${rid} OR video_id=${vid}) ====="
    docker logs --since "${since}" "${WORKER_C}" 2>/dev/null \
      | egrep "rid=${rid}|video_id=${vid}|start video_id=${vid}|done video_id=${vid}|ffmpeg|ffprobe" || true
    echo

    echo "===== RABBITMQ (${RABBIT_C}) (contains rid) ====="
    docker logs --since "${since}" "${RABBIT_C}" 2>/dev/null \
      | egrep "${rid}|x-request-id|x-trace-id|video\.process" || true
    echo
  } > "${prefix}_TRACE.txt"

  # Отдельные файлы
  docker logs --since "${since}" "${WEB_C}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}" > "${prefix}_web.log" || true

  docker logs --since "${since}" "${OUTBOX_C}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}|video\.process|published|outbox" > "${prefix}_outbox.log" || true

  docker logs --since "${since}" "${WORKER_C}" 2>/dev/null \
    | egrep "rid=${rid}|video_id=${vid}|start video_id=${vid}|done video_id=${vid}|ffmpeg|ffprobe" > "${prefix}_worker.log" || true

  docker logs --since "${since}" "${RABBIT_C}" 2>/dev/null \
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

FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

CLIENT_UPLOAD_ID="$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"

TOKEN="$(docker-compose -f docker-compose.ci.yml exec -T web \
  python3 -c "from service.security import create_access_token; print(create_access_token(user_id=1, expires_minutes=120))")"
AUTH_HEADER="Authorization: Bearer $TOKEN"

mkdir -p "$LOG_DIR"
echo "$TOKEN" > "${LOG_DIR}/last_jwt.txt"
chmod 600 "${LOG_DIR}/last_jwt.txt" || true

echo "Using JWT: $TOKEN"
echo "JWT saved to: ${LOG_DIR}/last_jwt.txt"
echo "CLIENT_UPLOAD_ID=$CLIENT_UPLOAD_ID"
echo "FILE=$FILE"
echo "FILENAME=$FILENAME"
echo "FILESIZE=$FILESIZE"

# ---------------- 1) PREPARE ----------------
echo "1) prepare..."
RESP="$(curl -sS -X POST "$BASE/videos/upload/prepare" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"test video\",\"filename\":\"$FILENAME\",\"file_size\":$FILESIZE,\"client_upload_id\":\"$CLIENT_UPLOAD_ID\"}")"

echo "$RESP" | jq .

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
echo "2) upload direct..."
curl -sS -X POST "$UPLOAD_URL" \
  -H "$AUTH_HEADER" \
  -F "file=@$FILE" | jq .

# md5 as ETag (local storage)
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
echo "3) complete (capture RID/TID)..."
COMPLETE_RAW="$(curl -sS -i -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"

# split headers/body, strip CR
COMPLETE_HEADERS="$(echo "$COMPLETE_RAW" | tr -d '\r' | sed -n '1,/^$/p')"
COMPLETE_BODY="$(echo "$COMPLETE_RAW" | tr -d '\r' | sed -n '/^$/,$p' | tail -n +2)"

RID="$(echo "$COMPLETE_HEADERS" | awk -F': ' 'tolower($1)=="x-request-id"{print $2; exit}')"
TID="$(echo "$COMPLETE_HEADERS" | awk -F': ' 'tolower($1)=="x-trace-id"{print $2; exit}')"

echo "RID=$RID"
echo "TID=$TID"
test -n "$RID" && test "$RID" != "null"

echo "$COMPLETE_BODY" | jq .

# Логи сразу после complete
collect_logs "after_complete" "$RID" "$VIDEO_ID" "$LOG_SINCE_DEFAULT" "$LOG_DIR"

# ---------------- 3.1) COMPLETE AGAIN (IDEMPOTENCY) ----------------
echo "3.1) complete again (idempotency check)..."
COMPLETE_2="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"
echo "$COMPLETE_2" | jq .

# ---------------- 4) WAIT READY ----------------
echo "4) wait READY..."
for i in $(seq 1 "$ATTEMPTS"); do
  INFO="$(curl -sS -X GET "$BASE/videos/${VIDEO_ID}" -H "$AUTH_HEADER")"
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

INFO="$(curl -sS -X GET "$BASE/videos/${VIDEO_ID}" -H "$AUTH_HEADER")"
STATUS="$(echo "$INFO" | jq -r '.status')"

if [[ "$STATUS" != "ready" ]]; then
  echo "❌ Not READY after wait. Last status=$STATUS"
  echo "$INFO" | jq .
  collect_logs "on_fail" "$RID" "$VIDEO_ID" "30m" "$LOG_DIR"
  exit 1
fi

# Логи после READY (полезно ловить worker/outbox completion)
collect_logs "after_ready" "$RID" "$VIDEO_ID" "$LOG_SINCE_DEFAULT" "$LOG_DIR"

HLS_URL="$(echo "$INFO" | jq -r '.hls_url // empty')"

echo
echo "==== LINKS (AUTH) ===="
echo "watch:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/watch"
echo "json:       http://localhost:8000/api/v1/videos/${VIDEO_ID}"
echo "mp4:        http://localhost:8000/api/v1/videos/${VIDEO_ID}/file"
echo "thumb:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/thumbnail"
echo "hls:        ${HLS_URL:-http://localhost:8000/api/v1/videos/${VIDEO_ID}/hls/master.m3u8}"
echo

# ---------------- 5) SHARE ----------------
echo "5) create share link..."
SHARE_RESP="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/share" -H "$AUTH_HEADER")"
echo "$SHARE_RESP" | jq .

SHARE_URL="$(echo "$SHARE_RESP" | jq -r '.share_url')"
SHARE_TOKEN="$(echo "$SHARE_URL" | sed -E 's#.*/shared/##')"
test -n "$SHARE_TOKEN" && test "$SHARE_TOKEN" != "null"

echo
echo "==== LINKS (SHARED) ===="
echo "shared watch:  http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/watch"
echo "shared json:   http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}"
echo "shared mp4:    http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/file"
echo "shared thumb:  http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/thumbnail"
echo "shared hls:    http://localhost:8000/api/v1/videos/shared/${SHARE_TOKEN}/hls/master.m3u8"
echo