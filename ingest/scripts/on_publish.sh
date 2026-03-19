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
THUMB_FILE="${OUT_DIR}/thumb.jpg"

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

# чистим старые HLS-артефакты и старый thumbnail на случай повторного старта того же stream_key
rm -f "${OUT_DIR}"/*.m3u8 "${OUT_DIR}"/*.ts "${OUT_DIR}"/*.jpg 2>/dev/null || true

log "starting transcoder via /opt/transcode.sh for stream='${NAME}'"

(
  exec /opt/transcode.sh "$NAME"
) >> "$SLOG" 2>&1 &

FFPID="$!"
echo "$FFPID" > "$PID_FILE" 2>/dev/null || true

log "transcoder started pid=${FFPID} pid_file=${PID_FILE}"

# ---- отдельная попытка снять один snapshot ----
(
  RTMP_HOST="${RTMP_HOST:-127.0.0.1}"
  RTMP_PORT="${RTMP_PORT:-1935}"
  INPUT_URL="rtmp://${RTMP_HOST}:${RTMP_PORT}/live/${NAME}"

  SNAP_MAX_ATTEMPTS="${SNAP_MAX_ATTEMPTS:-20}"
  SNAP_SLEEP_SECONDS="${SNAP_SLEEP_SECONDS:-1}"

  i=1
  while [ "$i" -le "$SNAP_MAX_ATTEMPTS" ]; do
    if [ -f "$THUMB_FILE" ] && [ -s "$THUMB_FILE" ]; then
      log "snapshot already exists file=${THUMB_FILE}"
      exit 0
    fi

    log "snapshot attempt=${i} input=${INPUT_URL} output=${THUMB_FILE}"

    TMP_THUMB="${THUMB_FILE}.tmp"

    if /usr/bin/ffmpeg -hide_banner -loglevel error -y \
      -rtmp_live live \
      -i "${INPUT_URL}" \
      -map 0:v:0 \
      -frames:v 1 \
      -q:v 2 \
      -f image2 \
      "${TMP_THUMB}" >> "$SLOG" 2>&1; then
      if [ -f "${TMP_THUMB}" ] && [ -s "${TMP_THUMB}" ]; then
        mv -f "${TMP_THUMB}" "${THUMB_FILE}"
        log "snapshot created file=${THUMB_FILE}"
        exit 0
      fi
    fi

    rm -f "${TMP_THUMB}" 2>/dev/null || true
    sleep "$SNAP_SLEEP_SECONDS"
    i=$((i + 1))
  done

  log "WARN snapshot not created for stream='${NAME}'"
  exit 0
) >> "$SLOG" 2>&1 &

log "snapshot worker started for stream='${NAME}'"
exit 0