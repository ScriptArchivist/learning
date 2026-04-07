#!/bin/sh
set -eu

mkdir -p /var/log/nginx
touch /var/log/nginx/error.log || true

mkdir -p /app/uploads
mkdir -p /app/uploads/live

chmod 0777 /app/uploads || true
chmod 0777 /app/uploads/live || true

exec nginx -g "daemon off;"