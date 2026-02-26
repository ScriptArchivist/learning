#!/bin/sh
set -eu

# volume может прийти с root-only правами
mkdir -p /app/uploads
chmod 0777 /app/uploads || true

# на всякий случай — чтобы live тоже мог создаваться
mkdir -p /app/uploads/live
chmod 0777 /app/uploads/live || true

exec nginx -g "daemon off;"