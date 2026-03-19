#!/bin/sh
set -eu

STREAM_KEY="${1:-}"
[ -n "${STREAM_KEY:-}" ] || { echo "transcode: empty stream key" >&2; exit 1; }

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
umask 000

RTMP_HOST="${RTMP_HOST:-127.0.0.1}"
RTMP_PORT="${RTMP_PORT:-1935}"

INPUT_URL="rtmp://${RTMP_HOST}:${RTMP_PORT}/live/${STREAM_KEY}"
OUT_DIR="/app/uploads/live/${STREAM_KEY}"
MASTER="${OUT_DIR}/master.m3u8"

mkdir -p "${OUT_DIR}"

# убираем старые артефакты, чтобы не было stale playlist
rm -f "${OUT_DIR}"/*.m3u8 "${OUT_DIR}"/*.ts 2>/dev/null || true

FFMPEG_PID=""

stop_ffmpeg() {
  if [ -n "${FFMPEG_PID:-}" ]; then
    kill "${FFMPEG_PID}" 2>/dev/null || true
    sleep 1
    kill -0 "${FFMPEG_PID}" 2>/dev/null && kill -9 "${FFMPEG_PID}" 2>/dev/null || true
  fi
}

on_term() {
  stop_ffmpeg
  exit 0
}

trap on_term INT TERM

ATTEMPT=0
MAX_ATTEMPTS="${MAX_ATTEMPTS:-20}"

while [ "$ATTEMPT" -lt "$MAX_ATTEMPTS" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "transcode: attempt=${ATTEMPT} input=${INPUT_URL} output=${MASTER}" >&2

  /usr/bin/ffmpeg -hide_banner -loglevel info -y \
    -rtmp_live live \
    -fflags +genpts \
    -use_wallclock_as_timestamps 1 \
    -i "${INPUT_URL}" \
    -map 0:v:0 -map 0:a:0? \
    -c:v libx264 \
    -preset veryfast \
    -tune zerolatency \
    -pix_fmt yuv420p \
    -g 48 \
    -keyint_min 48 \
    -sc_threshold 0 \
    -c:a aac \
    -ar 48000 \
    -ac 2 \
    -f hls \
    -hls_time 2 \
    -hls_list_size 6 \
    -hls_flags delete_segments+append_list+independent_segments \
    -hls_segment_type mpegts \
    -hls_segment_filename "${OUT_DIR}/seg_%05d.ts" \
    "${MASTER}" &

  FFMPEG_PID="$!"
  wait "${FFMPEG_PID}" || true
  RC=$?
  FFMPEG_PID=""

  if [ -f "${MASTER}" ]; then
    echo "transcode: master playlist created for ${STREAM_KEY}" >&2
    exit 0
  fi

  echo "transcode: ffmpeg exited rc=${RC}, retrying..." >&2
  sleep 1
done

echo "transcode: failed to create HLS for ${STREAM_KEY} after ${MAX_ATTEMPTS} attempts" >&2
exit 1