# Этап 4.2 — Live Ingest hooks

## Цель
Ingest (nginx-rtmp + ffmpeg) автоматически:
1) создаёт live-сессию в live-api при начале RTMP publish,
2) пишет HLS сегменты в storage,
3) останавливает сессию и завершает ffmpeg при окончании publish.

## Pipeline
Publisher (ffmpeg/OBS) → RTMP ingest (nginx-rtmp) → exec_publish → on_publish.sh → (create session) + (ffmpeg pull → HLS)  
RTMP stop → exec_publish_done → on_publish_done.sh → stop session + stop ffmpeg pull

## Конфигурация ingest
Файл: `ingest/nginx.conf`

RTMP application `live`:
- `exec_publish /opt/scripts/on_publish.sh $name;`
- `exec_publish_done /opt/scripts/on_publish_done.sh $name;`

`$name` = `stream_key`.

## Скрипты хуков
### on_publish.sh
Файл: `ingest/scripts/on_publish.sh`
- best-effort `POST /live/sessions` в live-api
- старт ffmpeg pull: `rtmp://ingest:1935/live/<stream_key>`
- вывод HLS: `/app/uploads/live/<stream_key>/master.m3u8` + `seg_*.ts`
- PID: `/tmp/ffmpeg-live-<stream_key>.pid`

### on_publish_done.sh
Файл: `ingest/scripts/on_publish_done.sh`
- stop ffmpeg pull по pidfile
- best-effort `DELETE /live/sessions/{session_id}`

## API live-api
База: `http://live-api:8000`

- `POST /live/sessions`
  - body: `{ "stream_key": "<optional>", "ttl_seconds": 3600 }`
  - response: `{ "session": { "id", "stream_key", ... }, "rtmp_url", "hls_url" }`

- `DELETE /live/sessions/{session_id}`

- `GET /live/sessions/{stream_key}`

## Storage / пути (S3-friendly)
HLS:
- `live/<stream_key>/master.m3u8`
- `live/<stream_key>/seg_00001.ts`, ...

## Тестирование
Smoke: `tests/live_smoke.sh`

Запуск:
```bash
./tests/live_smoke.sh

Ожидаемый результат:
SUCCESS: live smoke test passed


---

## 3) `tests/live_smoke.sh` — финальная версия (если нужно ещё раз)

(она уже рабочая у тебя; просто фиксируем в репо как “эталон”)

```bash
#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8004/live/sessions}"

echo "Creating live session..."
resp="$(curl -fsS -X POST "$API_URL" -H "Content-Type: application/json" -d '{"ttl_seconds":3600}')"

SESSION_ID="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["id"])' "$resp")"
STREAM_KEY="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["session"]["stream_key"])' "$resp")"
RTMP_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["rtmp_url"])' "$resp")"
HLS_URL="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["hls_url"])' "$resp")"

echo "SESSION_ID=$SESSION_ID"
echo "STREAM_KEY=$STREAM_KEY"
echo "RTMP_URL=$RTMP_URL"
echo "HLS_URL=$HLS_URL"

LOG="/tmp/push_${STREAM_KEY}.log"

echo "Starting RTMP push..."
ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=1000:sample_rate=44100 -c:v libx264 -pix_fmt yuv420p -preset veryfast -g 48 -c:a aac -ar 44100 -f flv "$RTMP_URL" > "$LOG" 2>&1 &
PUSH_PID=$!

cleanup() {
  kill "$PUSH_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Waiting for HLS..."
ok=0
for i in $(seq 1 60); do
  code="$(curl -s -o "/tmp/master_${STREAM_KEY}.m3u8" -w '%{http_code}' "$HLS_URL" || true)"
  if [[ "$code" == "200" ]] && [[ -s "/tmp/master_${STREAM_KEY}.m3u8" ]] && grep -q '^#EXTINF' "/tmp/master_${STREAM_KEY}.m3u8"; then
    ok=1
    break
  fi
  sleep 1
done

if [[ "$ok" != "1" ]]; then
  echo "ERROR: HLS not ready"
  echo "---- ffmpeg push log ----"
  tail -n 80 "$LOG" || true
  exit 1
fi

echo "HLS playlist detected"

echo "Stopping push..."
kill "$PUSH_PID" >/dev/null 2>&1 || true
sleep 2

echo "Stopping live session..."
curl -fsS -X DELETE "$API_URL/$SESSION_ID" >/dev/null

echo "SUCCESS: live smoke test passed"