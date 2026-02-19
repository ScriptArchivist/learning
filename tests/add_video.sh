#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8000/api/v1"
FILE="/home/vadim/Downloads/video5204062485010747752.mp4"
FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

# ✅ idempotency key для prepare (стабильный на запуск)
# Можно сделать фиксированным для повторного запуска (проверка идемпотентности),
# или случайным (каждый раз новый upload). Тут сделаем случайным:
CLIENT_UPLOAD_ID="$(python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"

# Получаем JWT из web-контейнера (без TTY)
TOKEN="$(docker-compose -f docker-compose.ci.yml exec -T web \
  python3 -c "from service.security import create_access_token; print(create_access_token(user_id=1, expires_minutes=120))")"
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "Using JWT: ${TOKEN:0:24}..."
echo "CLIENT_UPLOAD_ID=$CLIENT_UPLOAD_ID"
echo "FILE=$FILE"
echo "FILENAME=$FILENAME"
echo "FILESIZE=$FILESIZE"

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

# upload_url обычно относительный, делаем абсолютный
if [[ "$UPLOAD_URL" == /* ]]; then
  UPLOAD_URL="http://localhost:8000$UPLOAD_URL"
fi

echo "VIDEO_ID=$VIDEO_ID"
echo "UPLOAD_ID=$UPLOAD_ID"
echo "UPLOAD_URL=$UPLOAD_URL"
if [[ -n "$OBJECT_KEY" ]]; then
  echo "OBJECT_KEY=$OBJECT_KEY"
fi

echo "2) upload direct..."
curl -sS -X POST "$UPLOAD_URL" \
  -H "$AUTH_HEADER" \
  -F "file=@$FILE" | jq .

# ✅ etag для local: md5 файла (совпадает с тем, что мы делали в StorageBackendAdapter.get_object_metadata)
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

echo "3) complete..."
COMPLETE_RESP="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"

echo "$COMPLETE_RESP" | jq .

echo "3.1) complete again (idempotency check)..."
COMPLETE_RESP_2="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"

echo "$COMPLETE_RESP_2" | jq .

echo "4) wait READY..."
ATTEMPTS=60
SLEEP=1

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
  exit 1
fi

HLS_URL="$(echo "$INFO" | jq -r '.hls_url // empty')"

echo
echo "==== LINKS (AUTH) ===="
echo "watch:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/watch"
echo "json:       http://localhost:8000/api/v1/videos/${VIDEO_ID}"
echo "mp4:        http://localhost:8000/api/v1/videos/${VIDEO_ID}/file"
echo "thumb:      http://localhost:8000/api/v1/videos/${VIDEO_ID}/thumbnail"
echo "hls:        ${HLS_URL:-http://localhost:8000/api/v1/videos/${VIDEO_ID}/hls/master.m3u8}"
echo

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
