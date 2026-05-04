#!/usr/bin/env bash

set -euo pipefail

echo "🚀 HELM VIDEO PLATFORM SMOKE TEST START"

MINIKUBE_IP="$(minikube ip)"
HOST_NAME="${HOST_NAME:-video-platform.local}"
BASE_URL="http://${MINIKUBE_IP}"

HOST_HEADER="Host: ${HOST_NAME}"

WEB_BASE="${BASE_URL}/api"
VIDEO_API_BASE="${BASE_URL}/api/video/api/v1"
UPLOAD_BASE="${BASE_URL}/api/upload/api/v1"

FILE="${1:-/home/vadim/"Документы"/"Проектные документы"/video5204062485010747752.mp4}"

if [ ! -f "$FILE" ]; then
  echo "❌ File not found: $FILE"
  exit 1
fi

FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

echo "📍 MINIKUBE_IP=$MINIKUBE_IP"
echo "🌐 HOST=$HOST_NAME"
echo "📦 FILE=$FILE ($FILESIZE bytes)"

echo "👤 Ensuring test user exists..."

kubectl -n video-platform exec postgres-master-0 -- env PGPASSWORD=postgres \
psql -U postgres -d app -c "
insert into users (id, username, email, hashed_password, is_active, role, storage_limit, used_storage)
values (1, 'vadim', 'vadim@example.com', 'debug', true, 'user', 10737418240, 0)
on conflict (id) do nothing;
" >/dev/null

echo "✅ User ready"

echo "🔐 Generating JWT..."

TOKEN="$(kubectl -n video-platform exec deploy/web -- python3 -c '
import base64,hashlib,hmac,json,time
from src.config import settings

b64=lambda d: base64.urlsafe_b64encode(d).decode().rstrip("=")
sign=lambda m,s: hmac.new(s.encode(), m, hashlib.sha256).digest()

now=int(time.time())
header={"alg":"HS256","typ":"JWT"}
payload={
    "sub":"1",
    "iat":now,
    "exp":now+120*60,
    "iss":"identity-service",
    "aud":"video-platform",
    "role":"user"
}

hb=b64(json.dumps(header,separators=(",",":")).encode())
pb=b64(json.dumps(payload,separators=(",",":")).encode())
si=f"{hb}.{pb}".encode()

print(f"{hb}.{pb}.{b64(sign(si, settings.secret_key))}")
')"

AUTH_HEADER="Authorization: Bearer $TOKEN"

[ -n "$TOKEN" ] || { echo "❌ TOKEN EMPTY"; exit 1; }

echo "✅ JWT ready"

echo "🎬 Creating video..."

CREATE_RESP="$(curl -sS -X POST "${VIDEO_API_BASE}/videos" \
  -H "$HOST_HEADER" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"title":"helm smoke upload","description":"helm ingress test","visibility":"private"}')"

echo "$CREATE_RESP" | jq .

VIDEO_ID="$(echo "$CREATE_RESP" | jq -r '.id')"

[ "$VIDEO_ID" != "null" ] || { echo "❌ Failed to create video"; exit 1; }

echo "✅ VIDEO_ID=$VIDEO_ID"

echo "📤 Init upload..."

INIT_RAW="$(curl -sS -i -X POST \
  "${UPLOAD_BASE}/uploads/init?video_id=${VIDEO_ID}&filename=${FILENAME}" \
  -H "$HOST_HEADER" \
  -H "$AUTH_HEADER")"

INIT_BODY="$(echo "$INIT_RAW" | tr -d '\r' | sed -n '/^$/,$p' | tail -n +2)"

echo "$INIT_BODY" | jq .

UPLOAD_ID="$(echo "$INIT_BODY" | jq -r '.upload_id')"

[ "$UPLOAD_ID" != "null" ] || { echo "❌ Upload init failed"; exit 1; }

echo "✅ UPLOAD_ID=$UPLOAD_ID"

echo "📦 Uploading file..."

curl -sS -X POST "${UPLOAD_BASE}/uploads/${UPLOAD_ID}/file" \
  -H "$HOST_HEADER" \
  -F "file=@$FILE" >/dev/null

echo "✅ File uploaded"

echo "🏁 Completing upload..."

curl -sS -X POST \
  "${UPLOAD_BASE}/uploads/${UPLOAD_ID}/complete?size=${FILESIZE}&content_type=video/mp4" \
  -H "$HOST_HEADER" \
  -H "$AUTH_HEADER" | jq .

echo "✅ Upload completed"

echo "⏳ Waiting for processing..."

STATUS=""

for i in $(seq 1 60); do
  STATUS="$(curl -sS \
    "${VIDEO_API_BASE}/videos/${VIDEO_ID}?consistent=1" \
    -H "$HOST_HEADER" \
    -H "$AUTH_HEADER" | jq -r '.status')"

  echo "[$i/60] status=$STATUS"

  if [ "$STATUS" == "ready" ]; then
    echo "✅ Processing done"
    break
  fi

  sleep 2
done

if [ "$STATUS" != "ready" ]; then
  echo "❌ Processing timeout"
  exit 1
fi

echo "🎥 Checking playback..."

PLAYBACK_JSON="$(curl -sS \
  "${VIDEO_API_BASE}/videos/${VIDEO_ID}/playback?consistent=1" \
  -H "$HOST_HEADER" \
  -H "$AUTH_HEADER")"

echo "$PLAYBACK_JSON" | jq .

HLS_URL="$(echo "$PLAYBACK_JSON" | jq -r '.hls_url // empty')"

[ -n "$HLS_URL" ] || { echo "❌ No HLS URL"; exit 1; }

echo "🎯 HLS_URL=$HLS_URL"

if echo "$HLS_URL" | grep -q "192.168.1.12"; then
  echo "❌ HLS URL still contains old hardcoded IP"
  exit 1
fi

HLS_PATH="$(echo "$HLS_URL" | sed -E 's#^https?://[^/]+##')"

echo "📺 Validating HLS..."
echo "🔗 HLS_PATH=$HLS_PATH"

HTTP_CODE="$(curl -sS \
  -H "$HOST_HEADER" \
  -o /tmp/helm_master.m3u8 \
  -w '%{http_code}' \
  "${BASE_URL}${HLS_PATH}")"

[ "$HTTP_CODE" == "200" ] || {
  echo "❌ HLS not доступен, HTTP_CODE=$HTTP_CODE"
  exit 1
}

grep -q "#EXTM3U" /tmp/helm_master.m3u8 \
  && echo "✅ HLS playlist OK" \
  || { echo "❌ Invalid HLS"; exit 1; }

echo ""
echo "🎉 HELM SMOKE TEST PASSED SUCCESSFULLY"