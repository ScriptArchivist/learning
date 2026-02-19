#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8000/api/v1"
FILE="${FILE:-/home/vadim/Downloads/video5204062485010747752.mp4}"
FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

echo "BASE=$BASE"
echo "FILE=$FILE"
echo "FILENAME=$FILENAME"
echo "FILESIZE=$FILESIZE"
echo

echo "== 1) Get JWT =="
TOKEN="$(docker-compose -f docker-compose.ci.yml exec -T web \
  python3 -c "from service.security import create_access_token; print(create_access_token(user_id=1, expires_minutes=120))")"
AUTH_HEADER="Authorization: Bearer $TOKEN"
echo "JWT: ${TOKEN:0:40}..."
echo "$TOKEN" | awk -F. '{print "JWT parts:", NF}'
echo

echo "== 2) Prepare upload =="
PREP="$(curl -sS -X POST "$BASE/videos/upload/prepare" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"test video\",\"filename\":\"$FILENAME\",\"file_size\":$FILESIZE}")"
echo "$PREP" | jq .

VIDEO_ID="$(echo "$PREP" | jq -r '.video_id')"
UPLOAD_ID="$(echo "$PREP" | jq -r '.upload_id')"
OBJECT_KEY="$(echo "$PREP" | jq -r '.object_key // empty')"
test -n "$VIDEO_ID" && test "$VIDEO_ID" != "null"
test -n "$UPLOAD_ID" && test "$UPLOAD_ID" != "null"

echo "VIDEO_ID=$VIDEO_ID"
echo "UPLOAD_ID=$UPLOAD_ID"
[[ -n "$OBJECT_KEY" && "$OBJECT_KEY" != "null" ]] && echo "OBJECT_KEY=$OBJECT_KEY"
echo

echo "== 3) Upload direct =="
curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/direct" \
  -H "$AUTH_HEADER" \
  -F "file=@$FILE" | jq .
echo

echo "== 4) Complete upload =="
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
echo "ETAG=$ETAG"

COMPLETE="$(curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\",\"size_bytes\":$FILESIZE,\"etag\":\"$ETAG\"}")"
echo "$COMPLETE" | jq .
echo

echo "== 5) Wait READY =="
for i in $(seq 1 60); do
  INFO="$(curl -sS -H "$AUTH_HEADER" "$BASE/videos/${VIDEO_ID}")"
  ST="$(echo "$INFO" | jq -r '.status // empty' 2>/dev/null || true)"
  echo "[$i/60] status=$ST"
  [[ "$ST" == "ready" ]] && break
  sleep 1
done

INFO="$(curl -sS -H "$AUTH_HEADER" "$BASE/videos/${VIDEO_ID}")"
echo "$INFO" | jq .
STATUS="$(echo "$INFO" | jq -r '.status')"
if [[ "$STATUS" != "ready" ]]; then
  echo "❌ Not READY. status=$STATUS"
  exit 1
fi
echo "✅ READY"
echo

echo "== 6) AUTH HLS checks =="
echo "-- master.m3u8 (AUTH)"
curl -sS -i -H "$AUTH_HEADER" "$BASE/videos/${VIDEO_ID}/hls/master.m3u8" | sed -n '1,25p'
echo

V720_TOKEN="$(curl -sS -H "$AUTH_HEADER" "$BASE/videos/${VIDEO_ID}/hls/master.m3u8" \
  | grep -oP '720p/index\.m3u8\?token=\K[^ ]+' || true)"
echo "V720_TOKEN=${V720_TOKEN:-<not found>}"

if [[ -n "${V720_TOKEN:-}" ]]; then
  echo "-- 720p/index.m3u8 (AUTH)"
  curl -sS -i -H "$AUTH_HEADER" \
    "$BASE/videos/${VIDEO_ID}/hls/720p/index.m3u8?token=$V720_TOKEN" | sed -n '1,25p'
  echo

  TS_TOKEN="$(curl -sS -H "$AUTH_HEADER" \
    "$BASE/videos/${VIDEO_ID}/hls/720p/index.m3u8?token=$V720_TOKEN" \
    | grep -m1 -oP 'seg_\d+\.ts\?token=\K[^ ]+' || true)"
  echo "TS_TOKEN=${TS_TOKEN:-<not found>}"

  if [[ -n "${TS_TOKEN:-}" ]]; then
    echo "-- seg_00000.ts (AUTH, should be 200)"
    curl -sS -o /dev/null -w "HTTP %{http_code}\n" -I -H "$AUTH_HEADER" \
      "$BASE/videos/${VIDEO_ID}/hls/720p/seg_00000.ts?token=$TS_TOKEN"
    echo "-- seg_00000.ts without token (AUTH, should be 403)"
    curl -sS -o /dev/null -w "HTTP %{http_code}\n" -i -H "$AUTH_HEADER" \
      "$BASE/videos/${VIDEO_ID}/hls/720p/seg_00000.ts" | head -n 1
    echo
  fi
fi

echo "== 7) Create share link =="
SHARE_RESP="$(curl -sS -X POST -H "$AUTH_HEADER" "$BASE/videos/${VIDEO_ID}/share")"
echo "$SHARE_RESP" | jq .

SHARE_URL="$(echo "$SHARE_RESP" | jq -r '.share_url')"
SHARETOKEN="$(echo "$SHARE_URL" | sed -E 's#.*/shared/##')"
echo "SHARETOKEN=$SHARETOKEN"
echo

echo "== 8) SHARED HLS checks (no JWT) =="
echo "-- shared master.m3u8"
curl -sS -i "$BASE/videos/shared/${SHARETOKEN}/hls/master.m3u8" | sed -n '1,25p'
echo

SV720_TOKEN="$(curl -sS "$BASE/videos/shared/${SHARETOKEN}/hls/master.m3u8" \
  | grep -oP '720p/index\.m3u8\?token=\K[^ ]+' || true)"
echo "SV720_TOKEN=${SV720_TOKEN:-<not found>}"

if [[ -n "${SV720_TOKEN:-}" ]]; then
  echo "-- shared 720p/index.m3u8"
  curl -sS -i \
    "$BASE/videos/shared/${SHARETOKEN}/hls/720p/index.m3u8?token=$SV720_TOKEN" | sed -n '1,25p'
  echo

  STS_TOKEN="$(curl -sS \
    "$BASE/videos/shared/${SHARETOKEN}/hls/720p/index.m3u8?token=$SV720_TOKEN" \
    | grep -m1 -oP 'seg_\d+\.ts\?token=\K[^ ]+' || true)"
  echo "STS_TOKEN=${STS_TOKEN:-<not found>}"

  if [[ -n "${STS_TOKEN:-}" ]]; then
    echo "-- shared seg_00000.ts (should be 200)"
    curl -sS -o /dev/null -w "HTTP %{http_code}\n" -I \
      "$BASE/videos/shared/${SHARETOKEN}/hls/720p/seg_00000.ts?token=$STS_TOKEN"
    echo
  fi
fi

echo "==== LINKS ===="
echo "AUTH watch:   http://localhost:8000/api/v1/videos/${VIDEO_ID}/watch"
echo "AUTH json:    http://localhost:8000/api/v1/videos/${VIDEO_ID}"
echo "AUTH mp4:     http://localhost:8000/api/v1/videos/${VIDEO_ID}/file"
echo "AUTH thumb:   http://localhost:8000/api/v1/videos/${VIDEO_ID}/thumbnail"
echo "AUTH hls:     http://localhost:8000/api/v1/videos/${VIDEO_ID}/hls/master.m3u8"
echo
echo "SHARED watch: http://localhost:8000/api/v1/videos/shared/${SHARETOKEN}/watch"
echo "SHARED json:  http://localhost:8000/api/v1/videos/shared/${SHARETOKEN}"
echo "SHARED mp4:   http://localhost:8000/api/v1/videos/shared/${SHARETOKEN}/file"
echo "SHARED thumb: http://localhost:8000/api/v1/videos/shared/${SHARETOKEN}/thumbnail"
echo "SHARED hls:   http://localhost:8000/api/v1/videos/shared/${SHARETOKEN}/hls/master.m3u8"
