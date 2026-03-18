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
OUT_DIR="/app/uploads/live/${NAME}"

GRACE_SECONDS="${LIVE_DISCONNECT_GRACE_SECONDS:-20}"

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

log "grace wait start seconds='${GRACE_SECONDS}'"
sleep "$GRACE_SECONDS"

# Если за это время stream переподключился, новый on_publish уже создаст новый PID_FILE.
# Тогда disconnect старого publish не должен завершать новую live-сессию.
if [ -f "$PID_FILE" ]; then
  NEW_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${NEW_PID:-}" ] && kill -0 "$NEW_PID" 2>/dev/null; then
    log "reconnect detected, skip cleanup/disconnect new_pid=${NEW_PID}"
    exit 0
  fi
fi

if [ -d "$OUT_DIR" ]; then
  log "cleanup live artifacts dir='${OUT_DIR}'"
  rm -f "${OUT_DIR}"/*.m3u8 "${OUT_DIR}"/*.ts "${OUT_DIR}"/*.tmp 2>/dev/null || true
fi

LIVE_API_INTERNAL_BASE_URL="${LIVE_API_INTERNAL_BASE_URL:-http://live-api:8004}"
DISCONNECT_URL="${LIVE_API_INTERNAL_BASE_URL%/}/live/sessions/disconnect/${NAME}"
INTERNAL_TOKEN="${LIVE_INTERNAL_TOKEN:-}"

notify_disconnect() {
  if command -v curl >/dev/null 2>&1; then
    if [ -n "${INTERNAL_TOKEN}" ]; then
      curl -fsS -X POST -H "X-Live-Internal-Token: ${INTERNAL_TOKEN}" "$DISCONNECT_URL" >/dev/null
    else
      curl -fsS -X POST "$DISCONNECT_URL" >/dev/null
    fi
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    if [ -n "${INTERNAL_TOKEN}" ]; then
      wget -qO /dev/null \
        --method=POST \
        --header="X-Live-Internal-Token: ${INTERNAL_TOKEN}" \
        "$DISCONNECT_URL"
    else
      wget -qO /dev/null --method=POST "$DISCONNECT_URL"
    fi
    return 0
  fi

  return 1
}

if notify_disconnect; then
  log "live-api disconnect notified url='${DISCONNECT_URL}'"
else
  log "WARN failed to notify live-api disconnect url='${DISCONNECT_URL}'"
fi

log "on_publish_done done"
exit 0