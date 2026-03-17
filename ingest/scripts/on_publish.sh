#!/bin/sh
set -eu

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
umask 000

NAME="${1:-}"

PLOG="/app/uploads/live_exec.log"
SLOG="/app/uploads/live_exec_${NAME:-noname}.log"

log() {
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  echo "$ts $*" >> "$SLOG" 2>/dev/null || true
  echo "$ts $*" >> "$PLOG" 2>/dev/null || true
}

log "on_publish start name='${NAME}'"

[ -n "${NAME:-}" ] || { log "ERROR empty name"; exit 1; }
echo "$NAME" | grep -Eq '^[A-Za-z0-9_.-]+$' || { log "ERROR invalid name='$NAME'"; exit 1; }

OUT_DIR="/app/uploads/live/${NAME}"
PID_FILE="/tmp/ffmpeg-live-${NAME}.pid"
LOCK_DIR="/tmp/ffmpeg-live-${NAME}.lock"

# атомарный lock — чтобы не поднять второй transcoder на тот же stream_key
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "WARN lock exists ${LOCK_DIR} (another on_publish already running?)"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p "$OUT_DIR" || { log "ERROR mkdir failed ${OUT_DIR}"; exit 1; }

# если старый pid остался — добьём
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${OLD_PID:-}" ]; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
    kill -0 "$OLD_PID" 2>/dev/null && kill -9 "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" 2>/dev/null || true
fi

# чистим старые HLS-артефакты на случай повторного старта того же stream_key
rm -f "${OUT_DIR}"/*.m3u8 "${OUT_DIR}"/*.ts 2>/dev/null || true

log "starting transcoder via /opt/transcode.sh for stream='${NAME}'"

(
  exec /opt/transcode.sh "$NAME"
) >> "$SLOG" 2>&1 &

FFPID="$!"
echo "$FFPID" > "$PID_FILE" 2>/dev/null || true

log "transcoder started pid=${FFPID} pid_file=${PID_FILE}"
exit 0