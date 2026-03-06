```md
# Events

## Назначение

Документ описывает фактические доменные события, которые используются между сервисами через outbox и RabbitMQ.

Важно: этот документ ориентирован на текущую реализацию проекта, а не на абстрактную целевую модель.

Delivery semantics:
- `at-least-once`

Это означает, что consumer должен быть идемпотентным.

---

## Event transport

События:
- сохраняются в `outbox`
- публикуются `outbox-publisher`
- попадают в RabbitMQ
- обрабатываются consumer/worker сервисами

---

## Event envelope

В текущем коде используется envelope из `service.events.EventEnvelope` и outbox payload.

На практике event содержит как минимум:
- `event_type`
- `schema_version`
- `producer`
- `correlation_id`
- `trace_id`
- `payload`

Для processing worker особенно важен event:
- `video.process.requested`

---

## Correlation

Для логов и событий используются:
- `request_id`
- `trace_id`

Они прокидываются:
- из HTTP middleware
- в outbox events
- в RabbitMQ headers
- в worker/consumer logs

Это важно для отладки end-to-end потока.

---

## Основные события

## 1. `upload.completed`

Producer:
- `upload-service`

Consumer usage:
- downstream processing / event consumers

Payload fields:
- `upload_id`
- `video_id`
- `object_key`
- `size`
- `checksum`
- `content_type`

Назначение:
- сообщить, что файл загружен и подтверждён

---

## 2. `video.process.requested`

Producer:
- API/service layer через outbox

Consumer:
- `processing-worker`

Payload fields:
- `job_id`
- `video_id`
- `input_key`
- `output_prefix`
- `attempt`

Назначение:
- поставить задачу обработки видео в очередь

---

## 3. `video.process.completed`

Producer:
- `processing-worker`

Consumer:
- `video-events-consumer` / status update flows

Payload содержит информацию о завершённой обработке, включая:
- `video_id`
- metadata результата

Назначение:
- перевести видео в READY / обновить metadata

---

## 4. `video.process.failed`

Producer:
- `processing-worker`

Consumer:
- `video-events-consumer`

Payload:
- `video_id`
- `error` / `error_message`

Назначение:
- зафиксировать ошибку обработки
- перевести видео в FAILED

---

## 5. `live.session.started`

Producer:
- `live-api`

Payload fields:
- `session_id`
- `stream_key`
- `owner_id`
- `expires_at`

Назначение:
- зафиксировать старт live session

---

## 6. `live.session.stopped`

Producer:
- `live-api`

Payload fields:
- `session_id`
- `stream_key`
- `owner_id`
- `stopped_at`

Назначение:
- зафиксировать остановку live session

---

## 7. `live.session.expired`

Producer:
- `live-api` / cleaner flow

Payload fields:
- `session_id`
- `stream_key`
- `owner_id`
- `expired_at`

Назначение:
- зафиксировать TTL-expiration live session

---

## Idempotency

## HTTP layer
Идемпотентность явно поддерживается как минимум для:
- create live session через `Idempotency-Key`
- prepare/upload flows через `client_upload_id` и upload identifiers

## Worker / consumers
Consumer логика должна быть безопасна к повторной доставке.

В текущем коде это достигается через:
- DB claim / lock token
- проверку статуса
- lock TTL
- outbox retry model

---

## Что важно для Flutter

Flutter-клиент напрямую не работает с RabbitMQ событиями, но должен понимать их эффект на API-состояние.

Практически это означает:

### Upload flow
После upload complete клиент не получает READY мгновенно.  
Он должен опрашивать `video-api` до статуса:
- `ready`
или
- `failed`

### Live flow
После создания live session playback может стать доступен не мгновенно.  
Клиент должен опрашивать session/playback состояние.

---

## Recommended polling behavior for Flutter

### Video processing
Пока статус:
- `uploading`
- `uploaded`
- `processing`

повторять запрос `GET /videos/{id}` с интервалом 2–5 секунд.

### Live session
Пока live session активна, периодически проверять:
- `GET /live/sessions/{stream_key}`

---

## Summary

Для Flutter важнее не сами события, а их отражение в HTTP API:

- `upload.completed` → видео продвигается к `processing`
- `video.process.completed` → статус `ready`
- `video.process.failed` → статус `failed`
- `live.session.started/stopped/expired` → меняется состояние live session