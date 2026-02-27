#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker-compose -f docker-compose.ci.yml"
API_URL="${API_URL:-http://localhost:8000/api/v1/live/sessions}"
ORIGIN_BASE="${ORIGIN_BASE:-http://localhost:8080/live}"
RTMP_BASE="${RTMP_BASE:-rtmp://localhost:1935/live}"

resp="$(curl -fsS -X POST "$API_URL")"
STREAM_KEY="$(python -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$resp")"

HLS_URL="${ORIGIN_BASE}/${STREAM_KEY}/master.m3u8"
RTMP_URL="${RTMP_BASE}/${STREAM_KEY}"

echo "STREAM_KEY=$STREAM_KEY"
echo "RTMP_URL=$RTMP_URL"
echo "HLS_URL=$HLS_URL"

LOG="/tmp/push_${STREAM_KEY}.log"
nohup ffmpeg -nostdin -re \
  -f lavfi -i testsrc=size=1280x720:rate=30 \
  -f lavfi -i sine=frequency=1000:sample_rate=44100 \
  -c:v libx264 -preset veryfast -tune zerolatency \
  -c:a aac -ar 44100 \
  -f flv "$RTMP_URL" \
  >"$LOG" 2>&1 &
PUSH_PID=$!
echo "PUSH_PID=$PUSH_PID"
echo "PUSH_LOG=$LOG"

cleanup() {
  pkill -f "$RTMP_URL" >/dev/null 2>&1 || true
  kill "$PUSH_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

dump_ingest() {
  $COMPOSE exec -T -e K="$STREAM_KEY" ingest sh -lc '
    echo "== ingest: tail live_exec ==";
    tail -n 120 "/tmp/live_exec_${K}.log" 2>/dev/null || echo "no live_exec log";
    echo;
    echo "== ingest: outputs ==";
    ls -la "/app/uploads/live/${K}" 2>/dev/null || echo "no output dir";
    echo;
    echo "== ingest: pull ffmpeg ==";
    ps -o pid,args 2>/dev/null | grep -E "[f]fmpeg.*live/${K}" || echo "pull ffmpeg not running";
  ' || true
}

# ждём пока master.m3u8 станет 200 и появятся EXTINF + .ts
ok=0
for i in $(seq 1 60); do
  code="$(curl -s -o "/tmp/master_${STREAM_KEY}.m3u8" -w '%{http_code}' "$HLS_URL" || true)"
  if [[ "$code" == "200" ]] \
     && [[ -s "/tmp/master_${STREAM_KEY}.m3u8" ]] \
     && grep -q '^#EXTINF' "/tmp/master_${STREAM_KEY}.m3u8" \
     && grep -Eq '^[^#].+\.ts$' "/tmp/master_${STREAM_KEY}.m3u8"; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "$ok" != "1" ]]; then
  echo "ERROR: HLS master not ready/valid"
  echo "== curl head =="; curl -i "$HLS_URL" || true
  echo "== push log tail =="; tail -n 80 "$LOG" || true
  dump_ingest
  exit 1
fi

echo "== master.m3u8 head =="
sed -n '1,60p' "/tmp/master_${STREAM_KEY}.m3u8"

SEG="$(grep -E '^[^#].+\.ts$' "/tmp/master_${STREAM_KEY}.m3u8" | tail -n 1)"
SEG_URL="${ORIGIN_BASE}/${STREAM_KEY}/${SEG}"
curl -fsSI "$SEG_URL" >/dev/null
echo "OK: segment exists: $SEG_URL"

# stop push
pkill -f "$RTMP_URL" >/dev/null 2>&1 || true
sleep 2

# verify ingest: pull ffmpeg stopped and pidfile removed
ok2=0
for i in $(seq 1 30); do
  out="$($COMPOSE exec -T -e K="$STREAM_KEY" ingest sh -lc '
    alive="$(ps -o pid,args 2>/dev/null | grep -E "[f]fmpeg.*live/${K}" || true)"
    pidfile="/tmp/ffmpeg-live-${K}.pid"
    [ -n "$alive" ] && echo "FFMPEG_ALIVE=1" || echo "FFMPEG_ALIVE=0"
    [ -f "$pidfile" ] && echo "PIDFILE=1" || echo "PIDFILE=0"
  ')"
  echo "$out"
  if echo "$out" | grep -q 'FFMPEG_ALIVE=0' && echo "$out" | grep -q 'PIDFILE=0'; then
    ok2=1
    break
  fi
  sleep 1
done

if [[ "$ok2" != "1" ]]; then
  echo "ERROR: ingest did not stop correctly"
  dump_ingest
  exit 1
fi

echo "SUCCESS: smoke test passed for STREAM_KEY=$STREAM_KEY"
