#!/bin/sh
set -eu

mkdir -p /var/log/nginx
touch /var/log/nginx/error.log || true

mkdir -p /app/uploads
mkdir -p /app/uploads/live

# безопаснее чем 0777
chmod 0755 /app/uploads || true
chmod 0755 /app/uploads/live || true

exec nginx -g "daemon off;"