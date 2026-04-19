#!/usr/bin/env bash

set -euo pipefail

echo "🚀 K8S VIDEO PLATFORM SMOKE TEST START"

MINIKUBE_IP=$(minikube ip)

WEB_BASE="http://${MINIKUBE_IP}:30000/api/v1"
VIDEO_API_BASE="http://${MINIKUBE_IP}:30004/api/v1"
UPLOAD_BASE="http://${MINIKUBE_IP}:30003/api/v1"
ORIGIN_BASE="http://${MINIKUBE_IP}:30006"

FILE="${1:-/home/vadim/Downloads/video5204062485010747752.mp4}"

if [ ! -f "$FILE" ]; then
  echo "❌ File not found: $FILE"
  exit 1
fi

FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

echo "📍 MINIKUBE_IP=$MINIKUBE_IP"
echo "📦 FILE=$FILE ($FILESIZE bytes)"

# -------------------------------
# 1. Ensure user exists
# -------------------------------
echo "👤 Ensuring test user exists..."

kubectl exec postgres-master-0 -- env PGPASSWORD=postgres \
psql -U postgres -d app -c "
insert into users (id, username, email, hashed_password, is_active, role, storage_limit, used_storage)
values (1, 'vadim', 'vadim@example.com', 'debug', true, 'user', 10737418240, 0)
on conflict (id) do nothing;
" >/dev/null

echo "✅ User ready"

# -------------------------------
# 2. Generate JWT
# -------------------------------
echo "🔐 Generating JWT..."

TOKEN="$(kubectl exec deploy/web -- python3 -c '
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

# -------------------------------
# 3. Create video
# -------------------------------
echo "🎬 Creating video..."

CREATE_RESP="$(curl -sS -X POST "$VIDEO_API_BASE/videos" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"title":"k8s smoke upload","description":"k8s test","visibility":"private"}')"

echo "$CREATE_RESP" | jq .

VIDEO_ID="$(echo "$CREATE_RESP" | jq -r '.id')"

[ "$VIDEO_ID" != "null" ] || { echo "❌ Failed to create video"; exit 1; }

echo "✅ VIDEO_ID=$VIDEO_ID"

# -------------------------------
# 4. Init upload
# -------------------------------
echo "📤 Init upload..."

INIT_RAW="$(curl -sS -i -X POST \
  "$UPLOAD_BASE/uploads/init?video_id=${VIDEO_ID}&filename=${FILENAME}" \
  -H "$AUTH_HEADER")"

INIT_BODY="$(echo "$INIT_RAW" | tr -d '\r' | sed -n '/^$/,$p' | tail -n +2)"

echo "$INIT_BODY" | jq .

UPLOAD_ID="$(echo "$INIT_BODY" | jq -r '.upload_id')"

[ "$UPLOAD_ID" != "null" ] || { echo "❌ Upload init failed"; exit 1; }

echo "✅ UPLOAD_ID=$UPLOAD_ID"

# -------------------------------
# 5. Upload file
# -------------------------------
echo "📦 Uploading file..."

curl -sS -X POST "$UPLOAD_BASE/uploads/${UPLOAD_ID}/file" \
  -F "file=@$FILE" >/dev/null

echo "✅ File uploaded"

# -------------------------------
# 6. Complete upload
# -------------------------------
echo "🏁 Completing upload..."

curl -sS -X POST \
  "$UPLOAD_BASE/uploads/${UPLOAD_ID}/complete?size=${FILESIZE}&content_type=video/mp4" \
  -H "$AUTH_HEADER" | jq .

echo "✅ Upload completed"

# -------------------------------
# 7. Wait for processing
# -------------------------------
echo "⏳ Waiting for processing..."

for i in $(seq 1 60); do
  STATUS="$(curl -sS \
    "${VIDEO_API_BASE}/videos/${VIDEO_ID}?consistent=1" \
    -H "$AUTH_HEADER" | jq -r '.status')"

  echo "[$i/60] status=$STATUS"

  if [ "$STATUS" == "ready" ]; then
    echo "✅ Processing done"
    break
  fi

  sleep 2
done

# -------------------------------
# 8. Get playback
# -------------------------------
echo "🎥 Checking playback..."

PLAYBACK_JSON="$(curl -sS \
  "${VIDEO_API_BASE}/videos/${VIDEO_ID}/playback?consistent=1" \
  -H "$AUTH_HEADER")"

echo "$PLAYBACK_JSON" | jq .

HLS_URL="$(echo "$PLAYBACK_JSON" | jq -r '.hls_url // empty')"

[ -n "$HLS_URL" ] || { echo "❌ No HLS URL"; exit 1; }

echo "🎯 HLS_URL=$HLS_URL"

# -------------------------------
# 9. Validate HLS
# -------------------------------
echo "📺 Validating HLS..."

HTTP_CODE=$(curl -sS -o /tmp/k8s_master.m3u8 -w '%{http_code}' "$HLS_URL")

[ "$HTTP_CODE" == "200" ] || { echo "❌ HLS not доступен"; exit 1; }

grep -q "#EXTM3U" /tmp/k8s_master.m3u8 \
  && echo "✅ HLS playlist OK" \
  || { echo "❌ Invalid HLS"; exit 1; }

echo ""
echo "🎉 SMOKE TEST PASSED SUCCESSFULLY"