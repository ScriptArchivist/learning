#!/bin/bash

BASE_URL="http://192.168.1.12"

echo "1. Получаем токен..."
TOKEN=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"vadim","password":"password"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "TOKEN OK"

echo "2. Создаём live-сессию..."
RESPONSE=$(curl -s -X POST "$BASE_URL/live/sessions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"ttl_seconds":1800,"title":"auto-live"}')

echo "RESPONSE: $RESPONSE"

STREAM_KEY=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['stream_key'])")

echo "STREAM_KEY: $STREAM_KEY"

echo "3. Ищем видео..."
VIDEO=$(find /home/vadim -type f -iname "*.mp4" 2>/dev/null | head -n 1)

echo "VIDEO: $VIDEO"

echo "4. Запускаем стрим..."
ffmpeg -re -stream_loop -1 -i "$VIDEO" -c copy -f flv "rtmp://192.168.1.12:31935/live/$STREAM_KEY"