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
STATE_FILE="/tmp/live_session_${NAME}.id"

# stop pull ffmpeg
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${PID:-}" ]; then
    log "stopping ffmpeg pid=${PID}"
    kill "$PID" 2>/dev/null || true
    sleep 1
    kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" 2>/dev/null || true
fi

http_delete() {
  url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -sS --connect-timeout 2 --max-time 5 --retry 3 --retry-delay 0 --retry-all-errors \
      -X DELETE "$url" 2>>"$SLOG" >/dev/null || true
    return 0
  fi
  if command -v wget >/dev/null 2>&1; then
    # BusyBox wget: для DELETE проще сделать POST и игнорировать, поэтому если нет curl — просто best-effort skip
    log "WARN no curl for DELETE; skipping live-api stop"
    return 0
  fi
  log "WARN neither curl nor wget found; skipping live-api stop"
  return 0
}

# stop live-api session (best-effort)
if [ -f "$STATE_FILE" ]; then
  SESSION_ID="$(cat "$STATE_FILE" 2>/dev/null || true)"
  rm -f "$STATE_FILE" 2>/dev/null || true
  if [ -n "${SESSION_ID:-}" ]; then
    LIVE_API_URL_BASE="${LIVE_API_URL_BASE:-http://live-api:8000/live/sessions}"
    http_delete "${LIVE_API_URL_BASE}/${SESSION_ID}"
    log "live-api stop sent session_id=${SESSION_ID}"
  fi
fi

log "on_publish_done done"
exit 0