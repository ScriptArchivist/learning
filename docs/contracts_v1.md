# Contracts v1 (API + Events + Idempotency)

Версия документа: **v1**
Дата: **2026-03-02**

Цель: зафиксировать контракты (HTTP API + события) и гарантии (идемпотентность, корреляция), чтобы дальше разделять монолит на сервисы без догадок.

---

# 0. Термины и принципы

## 0.1 Контексты (bounded contexts)

Минимальный набор доменов:

- **identity** — пользователи, авторизация, права
- **video-api** — HTTP API для управления видео и их статусами
- **upload** — приём файла, формирование `input_key`, завершение загрузки
- **processing** — транскодирование, HLS, постобработка
- **live-api** — HTTP API для live-сессий
- **live-ingest** — ingest + HLS-live сегментация
- **outbox** — гарантированная публикация событий

---

## 0.2 Версионирование

- Все события содержат `schema_version: 1`
- `schema_version` — целое число
- Backward-compatible изменения: добавление необязательных полей
- Breaking changes → новая версия (2, 3, ...)

---

## 0.3 Корреляция и трассировка

Все HTTP-запросы и события используют:

- `correlation_id` — сквозной идентификатор запроса
- `causation_id` — что вызвало событие (request_id или event_id)
- `event_id` — UUID события

Правила:

- HTTP принимает `X-Correlation-Id`
- Если нет — генерируется на входе
- `correlation_id` прокидывается во все события
- `causation_id` = request_id для событий, вызванных HTTP

---

## 0.4 Идемпотентность

### HTTP

Клиент может отправлять `Idempotency-Key`.

Обязательные идемпотентные операции:

- POST /videos
- POST /videos/{video_id}/upload/complete
- POST /live/sessions
- POST /live/sessions/{id}/stop

Повтор с тем же ключом:
- возвращает тот же результат
- не создаёт дубликатов

---

### События

- Delivery: at-least-once
- У каждого события есть `idempotency_key`
- Consumer обязан быть идемпотентным

Способы:
- таблица processed_events
- уникальный индекс
- естественный ключ (job_id, session_id и т.д.)

---

# 1. Event Envelope v1

Все события публикуются в едином формате:

```json
{
  "event_id": "uuid",
  "event_type": "VIDEO_CREATED",
  "schema_version": 1,
  "occurred_at": "UTC ISO8601",
  "producer": "video-api",
  "correlation_id": "string",
  "causation_id": "string",
  "idempotency_key": "VIDEO_CREATED:video:123",
  "data": {}
}

Требования:

event_id — UUID

occurred_at — UTC ISO-8601

schema_version — integer

producer — имя сервиса

idempotency_key — обязателен

2. Processing Job Envelope v1

Сообщение в очередь processing:

{
  "job_id": "job_01J123...",
  "video_id": "123",
  "input_key": "uploads/42/123/source.mp4",
  "output_prefix": "videos/123/hls/",
  "attempt": 1
}

Гарантии:

Producer может отправить дубликаты

Worker обязан:

публиковать PROCESSING_STARTED один раз на job_id

не портить результат при повторе job_id

Если hls_master_key уже существует → считать job выполненной

3. HTTP Error Contract

Формат ошибки:

{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human readable message",
    "details": {},
    "correlation_id": "string"
  }
}

Коды:

VALIDATION_ERROR (400)

UNAUTHORIZED (401)

FORBIDDEN (403)

NOT_FOUND (404)

CONFLICT (409)

IDEMPOTENCY_REPLAY (409 или 200/201)

INTERNAL_ERROR (500)

4. Статусы

Видео:

CREATED

QUEUED

PROCESSING

READY

FAILED

Live session:

STARTED

STOPPED


---

