#!/bin/sh
set -eu

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
umask 000

NAME="${1:-}"

TMPLOG="/tmp/live_exec_${NAME:-noname}.log"
PLOG="/app/uploads/live_exec.log"

log() {
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  echo "$ts $*" >> "$TMPLOG" 2>/dev/null || true
  echo "$ts $*" >> "$PLOG" 2>/dev/null || true
}

log "on_publish start name='${NAME}'"

[ -n "${NAME:-}" ] || { log "ERROR empty name"; exit 1; }
echo "$NAME" | grep -Eq '^[A-Za-z0-9_.-]+$' || { log "ERROR invalid name='$NAME'"; exit 1; }

OUT_DIR="/app/uploads/live/${NAME}"
PID_FILE="/tmp/ffmpeg-live-${NAME}.pid"
LOCK_DIR="/tmp/ffmpeg-live-${NAME}.lock"

# ВАЖНО: внутри docker-compose сети ходим по имени сервиса, а не 127.0.0.1
RTMP_HOST="${RTMP_HOST:-ingest}"
RTMP_PORT="${RTMP_PORT:-1935}"

IN_URL="rtmp://${RTMP_HOST}:${RTMP_PORT}/live/${NAME}"

OUT_M3U8="${OUT_DIR}/master.m3u8"

# lock (атомарно)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "WARN lock exists ${LOCK_DIR} (another on_publish running?)"
  sleep 1
  mkdir "$LOCK_DIR" 2>/dev/null || { log "ERROR cannot acquire lock ${LOCK_DIR}"; exit 1; }
fi
cleanup() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

mkdir -p "$OUT_DIR" || { log "ERROR mkdir failed ${OUT_DIR}"; exit 1; }
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

probe_ok() {
  if command -v timeout >/dev/null 2>&1; then
    out="$(timeout 2 /usr/bin/ffprobe -v error -rtmp_live live -rw_timeout 2000000 \
      -show_entries stream=codec_type -of default=nw=1:nk=1 \
      "$IN_URL" 2>/dev/null || true)"
  else
    out="$(/usr/bin/ffprobe -v error -rtmp_live live -rw_timeout 2000000 \
      -show_entries stream=codec_type -of default=nw=1:nk=1 \
      "$IN_URL" 2>/dev/null || true)"
  fi

  # ВАЖНО: ждём именно video, иначе ffmpeg стартует как audio-only и потом видео уже не подцепит
  echo "$out" | grep -q '^video$'
}

WAIT="${WAIT_SECONDS:-20}"
log "waiting for input up to ${WAIT}s (ffprobe) url=${IN_URL}"
i=0
while [ "$i" -lt "$WAIT" ]; do
  if probe_ok; then
    log "ffprobe ok after ${i}s"
    break
  fi
  i=$((i+1))
  sleep 1
done

if [ "$i" -ge "$WAIT" ]; then
  log "ERROR input not available after ${WAIT}s: ${IN_URL}"
  exit 1
fi

log "starting ffmpeg in_url=${IN_URL} out=${OUT_M3U8}"

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
) >> "$TMPLOG" 2>&1 &

FFPID="$!"
echo "$FFPID" > "$PID_FILE" 2>/dev/null || true
log "ffmpeg started pid=${FFPID} (pid_file=${PID_FILE})"

sleep 1
if ! kill -0 "$FFPID" 2>/dev/null; then
  log "ERROR ffmpeg exited immediately pid=${FFPID} (see output above)"
  rm -f "$PID_FILE" 2>/dev/null || true
  exit 1
fi

log "on_publish done (ok)"
exit 0