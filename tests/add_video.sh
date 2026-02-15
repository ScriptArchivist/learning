#!/usr/bin/env bash

set -euo pipefail

BASE="http://localhost:8000/api/v1"
FILE="/home/vadim/Downloads/video5204062485010747752.mp4"
FILENAME="$(basename "$FILE")"
FILESIZE="$(stat -c%s "$FILE")"

echo "1) prepare..."
RESP="$(curl -sS -X POST "$BASE/videos/upload/prepare" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"test video\",\"filename\":\"$FILENAME\",\"file_size\":$FILESIZE}")"

echo "$RESP" | jq .

VIDEO_ID="$(echo "$RESP" | jq -r '.video_id // .id')"
UPLOAD_ID="$(echo "$RESP" | jq -r '.upload_id')"
UPLOAD_URL="$(echo "$RESP" | jq -r '.upload_url')"

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

echo "2) upload direct..."
curl -sS -X POST "$UPLOAD_URL" \
  -F "file=@$FILE" | jq .

echo "3) complete..."
curl -sS -X POST "$BASE/videos/${VIDEO_ID}/upload/complete" \
  -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$UPLOAD_ID\"}" | jq .
