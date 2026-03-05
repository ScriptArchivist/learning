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
    if ps -o pid,args 2>/dev/null | awk -v p="$PID" -v n="$NAME" '
      $1==p && $0 ~ /ffmpeg/ && $0 ~ ("/live/" n) && $0 ~ /-f hls/ { found=1 }
      END { exit(found?0:1) }
    '; then
      log "stopping ffmpeg pid=${PID}"
      kill "$PID" 2>/dev/null || true
      sleep 1
      kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null || true
    else
      log "WARN pid=${PID} not our ffmpeg; not killing"
    fi
  fi
  rm -f "$PID_FILE" 2>/dev/null || true
fi

# stop live session in live-api (best-effort)
if [ -f "$STATE_FILE" ]; then
  SESSION_ID="$(cat "$STATE_FILE" 2>/dev/null || true)"
  rm -f "$STATE_FILE" 2>/dev/null || true

  if [ -n "${SESSION_ID:-}" ]; then
    LIVE_API_BASE="${LIVE_API_URL_BASE:-http://live-api:8000/live/sessions}"
    CORR_ID="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo $$)"

    curl -sS -X DELETE "${LIVE_API_BASE}/${SESSION_ID}" \
      -H "X-Correlation-Id: ${CORR_ID}" \
      >/dev/null 2>&1 || true

    log "live-api stop sent session_id=${SESSION_ID}"
  fi
fi

log "on_publish_done done"
exit 0