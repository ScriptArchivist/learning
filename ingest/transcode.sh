#!/bin/sh
set -eu

# список ключей для MVP (можно расширять)
STREAM_KEYS="${STREAM_KEYS:-test123}"

# можно переопределять снаружи, но по умолчанию как и было
HLS_ROOT="${HLS_ROOT:-/app/uploads/live}"

mkdir -p "$HLS_ROOT"

for KEY in $STREAM_KEYS; do
  mkdir -p "${HLS_ROOT}/${KEY}"

  (
    echo "starting live transcode for ${KEY}"
    ffmpeg -hide_banner -loglevel info -y \
      -fflags nobuffer \
      -rtmp_live live \
      -i "rtmp://ingest:1935/live/${KEY}" \
      -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
      -g 48 -keyint_min 48 -sc_threshold 0 \
      -c:a aac -ar 48000 -ac 2 \
      -f hls \
      -hls_time 2 \
      -hls_list_size 6 \
      -hls_flags delete_segments+append_list+independent_segments \
      -hls_segment_type mpegts \
      -hls_segment_filename "${HLS_ROOT}/${KEY}/seg_%05d.ts" \
      "${HLS_ROOT}/${KEY}/master.m3u8"
  ) &
done

wait