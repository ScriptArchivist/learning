#!/bin/sh
set -eu

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
umask 000

NAME="${1:-}"

# Логи только в /app/uploads (гарантированно доступно по entrypoint chmod 0777)
PLOG="/app/uploads/live_exec.log"
SLOG="/app/uploads/live_exec_${NAME:-noname}.log"

log() {
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  # НИКОГДА не падаем из-за логов
  echo "$ts $*" >> "$SLOG" 2>/dev/null || true
  echo "$ts $*" >> "$PLOG" 2>/dev/null || true
}

log "on_publish start name='${NAME}'"

[ -n "${NAME:-}" ] || { log "ERROR empty name"; exit 0; }
echo "$NAME" | grep -Eq '^[A-Za-z0-9_.-]+$' || { log "ERROR invalid name='$NAME'"; exit 0; }

OUT_DIR="/app/uploads/live/${NAME}"
PID_FILE="/tmp/ffmpeg-live-${NAME}.pid"
LOCK_DIR="/tmp/ffmpeg-live-${NAME}.lock"

# ---- live-api create (best-effort) ----
LIVE_API_URL="${LIVE_API_URL:-http://live-api:8000/live/sessions}"
CORR_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$)"
STATE_FILE="/tmp/live_session_${NAME}.id"

# ttl_seconds обязателен (иначе 422)
resp="$(curl -sS -X POST "$LIVE_API_URL" \
  -H "Content-Type: application/json" \
  -H "X-Correlation-Id: $CORR_ID" \
  -d "{\"stream_key\":\"${NAME}\",\"ttl_seconds\":3600}" 2>/dev/null || true)"

session_id="$(echo "$resp" | python3 -c 'import sys,json; 
import sys
s=sys.stdin.read().strip()
if not s: 
  sys.exit(0)
d=json.loads(s)
print(d.get("session",{}).get("id",""))' 2>/dev/null || true)"

if [ -n "${session_id:-}" ]; then
  echo "$session_id" > "$STATE_FILE" 2>/dev/null || true
  log "live-api create ok session_id=${session_id} corr_id=${CORR_ID}"
else
  log "WARN live-api create failed (continuing). resp='${resp}'"
fi
# ---- /live-api create ----

# lock (атомарно)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "WARN lock exists ${LOCK_DIR} (another on_publish running?)"
  sleep 1
  mkdir "$LOCK_DIR" 2>/dev/null || { log "ERROR cannot acquire lock ${LOCK_DIR}"; exit 0; }
fi
cleanup() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$OUT_DIR" || { log "ERROR mkdir failed ${OUT_DIR}"; exit 0; }
log "created OUT_DIR=${OUT_DIR}"

# остановим старый ffmpeg (если он реально наш)
stop_old() {
  [ -f "$PID_FILE" ] || return 0
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "${OLD_PID:-}" ] || { rm -f "$PID_FILE" 2>/dev/null || true; return 0; }

  if ps -o pid,args 2>/dev/null | awk -v p="$OLD_PID" -v n="$NAME" '
    $1==p && $0 ~ /ffmpeg/ && $0 ~ ("/live/" n) { found=1 }
    END { exit(found?0:1) }
  '; then
    log "stopping old ffmpeg pid=${OLD_PID}"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
    kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID" 2>/dev/null || true
  else
    log "WARN old pidfile pid=${OLD_PID} is not our ffmpeg; not killing"
  fi

  rm -f "$PID_FILE" 2>/dev/null || true
}

stop_old

RTMP_HOST="${RTMP_HOST:-ingest}"
RTMP_PORT="${RTMP_PORT:-1935}"
IN_URL="rtmp://${RTMP_HOST}:${RTMP_PORT}/live/${NAME}"
OUT_M3U8="${OUT_DIR}/master.m3u8"

log "starting ffmpeg pull in_url=${IN_URL} out=${OUT_M3U8}"

(
  exec /usr/bin/ffmpeg -hide_banner -loglevel info -y \
    -rtmp_live live \
    -rw_timeout 5000000 \
    -fflags +genpts \
    -use_wallclock_as_timestamps 1 \
    -i "$IN_URL" \
    -map 0:v:0? -map 0:a:0? \
    -vf "setpts=PTS-STARTPTS" \
    -af "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0" \
    -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
    -g 48 -keyint_min 48 -sc_threshold 0 \
    -c:a aac -ar 48000 -ac 2 \
    -f hls \
    -hls_time 2 \
    -hls_list_size 6 \
    -hls_flags delete_segments+append_list+independent_segments \
    -hls_segment_type mpegts \
    -hls_segment_filename "${OUT_DIR}/seg_%05d.ts" \
    "$OUT_M3U8"
) >> "$SLOG" 2>&1 &

FFPID="$!"
echo "$FFPID" > "$PID_FILE" 2>/dev/null || true
log "ffmpeg pull started pid=${FFPID} pid_file=${PID_FILE}"

exit 0