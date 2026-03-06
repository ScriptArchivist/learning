```md
# Live API

## Service

`live-api`

Base URL example:
- local: `http://localhost:8004`
- home LAN: `http://<LAN_IP>:8004`

Swagger:
- `/docs`

---

## Назначение

Сервис отвечает за live session lifecycle:

- создать live session
- получить live session
- остановить live session

---

## Authentication

В `web/live.py` используется `service.security.get_current_user`.

Значит live endpoints следует считать приватными.

---

## Models

### LiveSessionCreateRequest

```json
{
  "stream_key": "optional",
  "ttl_seconds": 1800
}

stream_key — optional, если не передан, будет сгенерирован

ttl_seconds — lifetime session, минимум 60, максимум 86400

LiveSessionDTO
{
  "id": 1,
  "owner_id": 1,
  "stream_key": "abc",
  "status": "started",
  "created_at": "2026-03-01T10:00:00Z",
  "started_at": "2026-03-01T10:00:00Z",
  "stopped_at": null,
  "expires_at": "2026-03-01T10:30:00Z",
  "error": null
}
LiveSessionCreateResponse
{
  "session": {},
  "rtmp_url": "rtmp://...",
  "hls_url": "http://..."
}
Endpoints
POST /live/sessions

Создать live session.

Headers

Optional:

Idempotency-Key

Request body
{
  "stream_key": null,
  "ttl_seconds": 1800
}
Response
{
  "session": {
    "id": 1,
    "owner_id": 1,
    "stream_key": "generated-key",
    "status": "started",
    "created_at": "...",
    "started_at": "...",
    "stopped_at": null,
    "expires_at": "...",
    "error": null
  },
  "rtmp_url": "rtmp://localhost:1935/live/generated-key",
  "hls_url": "http://localhost:8080/live/generated-key/master.m3u8"
}
Important for Flutter

Flutter-клиент обычно не пушит RTMP сам, но этот endpoint важен чтобы:

получить hls_url для playback

показать session info

интегрироваться с внешним source/publisher в будущем

GET /live/sessions/{stream_key}

Получить live session по stream key.

Response

LiveSessionDTO

Useful for Flutter

polling текущего статуса

отображение информации о live session

проверка expired/stopped

DELETE /live/sessions/{session_id}

Остановить live session.

Response

HTTP 204 No Content

Meaning

session переводится в stopped

live storage cleanup выполняется на backend side

Recommended Flutter flow
Start live

POST /live/sessions

сохранить:

session.id

session.stream_key

hls_url

rtmp_url

Poll state

GET /live/sessions/{stream_key}

Stop live

DELETE /live/sessions/{session_id}

Playback

открыть hls_url в player

Status values

Возможные статусы:

created

started

stopped

expired

error

Flutter UI может отображать их как:

created → preparing

started → live

stopped → stopped

expired → expired

error → error