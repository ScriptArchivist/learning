#!/bin/sh
set -eu

# nginx expects /var/log/nginx to exist (otherwise it can fail on error_log)
mkdir -p /var/log/nginx || true
touch /var/log/nginx/error.log || true

# volume может прийти с root-only правами
mkdir -p /app/uploads
chmod 0777 /app/uploads || true

# на всякий случай — чтобы live тоже мог создаваться
mkdir -p /app/uploads/live
chmod 0777 /app/uploads/live || true

exec nginx -g "daemon off;"