#!/bin/sh
set -eu

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

NAME="${1:-}"
[ -n "${NAME:-}" ] || exit 0

PLOG="/app/uploads/live_exec.log"
SLOG="/app/uploads/live_exec_${NAME:-noname}.log"

log() {
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  echo "$ts $*" >> "$SLOG" 2>/dev/null || true
  echo "$ts $*" >> "$PLOG" 2>/dev/null || true
}

log "on_publish_done start name='${NAME}'"

PID_FILE="/tmp/ffmpeg-live-${NAME}.pid"
LOCK_DIR="/tmp/ffmpeg-live-${NAME}.lock"

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ]; then
    log "stopping transcoder pid=${PID}"
    kill "$PID" 2>/dev/null || true
    sleep 1
    kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" 2>/dev/null || true
fi

rmdir "$LOCK_DIR" 2>/dev/null || true

log "on_publish_done done"
exit 0