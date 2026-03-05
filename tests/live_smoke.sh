#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8004/live/sessions}"

echo "Creating live session..."
resp="$(curl -fsS -X POST "$API_URL" -H "Content-Type: application/json" -d '{"ttl_seconds":3600}')"

SESSION_ID="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["id"])' "$resp")"
STREAM_KEY="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$resp")"
RTMP_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["rtmp_url"])' "$resp")"
HLS_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["hls_url"])' "$resp")"

echo "SESSION_ID=$SESSION_ID"
echo "STREAM_KEY=$STREAM_KEY"
echo "RTMP_URL=$RTMP_URL"
echo "HLS_URL=$HLS_URL"

LOG="/tmp/push_${STREAM_KEY}.log"

echo "Starting RTMP push..."
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=1000:sample_rate=44100 -c:v libx264 -pix_fmt yuv420p -preset veryfast -g 48 -c:a aac -ar 44100 -f flv "$RTMP_URL" > "$LOG" 2>&1 &
PUSH_PID=$!

cleanup() {
  kill "$PUSH_PID" >/dev/null 2>&1 || true
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
curl -fsS -X DELETE "$API_URL/$SESSION_ID" >/dev/null

echo "SUCCESS: live smoke test passed"