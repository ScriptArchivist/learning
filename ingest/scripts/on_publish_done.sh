#!/bin/sh
set -eu

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

NAME="${1:-}"
[ -n "${NAME:-}" ] || exit 0

PID_FILE="/tmp/ffmpeg-live-${NAME}.pid"

# лог (в тот же файл, что и on_publish)
TMPLOG="/tmp/live_exec_${NAME:-noname}.log"
PLOG="/app/uploads/live_exec.log"
log() {
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  echo "$ts $*" >> "$TMPLOG" 2>/dev/null || true
  echo "$ts $*" >> "$PLOG" 2>/dev/null || true
}

log "on_publish_done start name='${NAME}'"

[ -f "$PID_FILE" ] || { log "on_publish_done: no pidfile (nothing to stop)"; exit 0; }

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
[ -n "${PID:-}" ] || { log "on_publish_done: empty pidfile; removing"; rm -f "$PID_FILE" 2>/dev/null || true; exit 0; }

# Проверяем, что PID — это именно ffmpeg нашего стрима (защита от гонок/реюза PID)
# BusyBox ps не умеет -p, поэтому сканируем весь вывод.
if ! ps -o pid,args 2>/dev/null | awk -v p="$PID" -v n="$NAME" '
  $1==p &&
  $0 ~ /ffmpeg/ &&
  $0 ~ ("/live/" n) &&
  $0 ~ /-f hls/ { found=1 }
  END { exit(found?0:1) }
'; then
  log "on_publish_done: pid=${PID} is not our ffmpeg; not killing; keeping pidfile"
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  log "on_publish_done: pid=${PID} already dead; removing pidfile"
  rm -f "$PID_FILE" 2>/dev/null || true
  exit 0
fi

log "on_publish_done: stopping ffmpeg pid=${PID}"
kill "$PID" 2>/dev/null || true
sleep 1
if kill -0 "$PID" 2>/dev/null; then
  kill -9 "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE" 2>/dev/null || true
log "on_publish_done: done"
exit 0