# ✅ Новый `docs/events.md` (заменить файл полностью)

```md
# Event Contract v1 (Outbox + RabbitMQ)

Документ фиксирует единый формат событий, которые:

- сохраняются в `outbox_events.payload`
- публикуются в RabbitMQ
- обрабатываются consumer'ами через строгий envelope

Delivery semantics: **at-least-once**

---

# 1. Event Envelope (schema_version=1)

```json
{
  "event_id": "uuid",
  "event_type": "VIDEO_CREATED",
  "schema_version": 1,
  "occurred_at": "UTC ISO8601",
  "producer": "video-api",
  "correlation_id": "string",
  "causation_id": "string",
  "idempotency_key": "string",
  "data": {}
}

Обязательные поля:

event_id (UUID)

event_type (enum)

schema_version (int)

occurred_at (UTC)

producer

idempotency_key

data (object)

2. Events v1
2.1 VIDEO_CREATED

Producer: video-api
Consumers: upload, processing

Idempotency key:
VIDEO_CREATED:video:{video_id}

{
  "video_id": "123",
  "owner_id": "42",
  "title": "My video",
  "created_at": "UTC ISO8601",
  "source": {
    "type": "upload",
    "input_key": "uploads/42/123/source.mp4"
  }
}
2.2 UPLOAD_COMPLETED

Producer: upload
Consumers: processing, video-api

Idempotency key:
UPLOAD_COMPLETED:video:{video_id}:input:{input_key}

{
  "video_id": "123",
  "owner_id": "42",
  "input_key": "uploads/42/123/source.mp4",
  "size_bytes": 10485760,
  "content_type": "video/mp4",
  "checksum": {
    "algo": "sha256",
    "value": "ab12..."
  },
  "completed_at": "UTC ISO8601"
}
2.3 PROCESSING_STARTED

Producer: processing
Consumers: video-api

Idempotency key:
PROCESSING_STARTED:job:{job_id}

{
  "job": {
    "job_id": "job_01J123...",
    "attempt": 1
  },
  "video_id": "123",
  "input_key": "uploads/42/123/source.mp4",
  "output_prefix": "videos/123/hls/",
  "started_at": "UTC ISO8601",
  "worker": {
    "service": "processing-worker",
    "instance_id": "hostname-or-pod"
  }
}
2.4 PROCESSING_DONE

Producer: processing
Consumers: video-api

Idempotency key:
PROCESSING_DONE:job:{job_id}

{
  "job": {
    "job_id": "job_01J123...",
    "attempt": 1
  },
  "video_id": "123",
  "output": {
    "output_prefix": "videos/123/hls/",
    "hls_master_key": "videos/123/hls/master.m3u8",
    "duration_ms": 120000,
    "video_codec": "h264",
    "audio_codec": "aac"
  },
  "finished_at": "UTC ISO8601"
}
2.5 PROCESSING_FAILED

Producer: processing
Consumers: video-api

Idempotency key:
PROCESSING_FAILED:job:{job_id}

{
  "job": {
    "job_id": "job_01J123...",
    "attempt": 2
  },
  "video_id": "123",
  "failed_at": "UTC ISO8601",
  "error": {
    "code": "FFMPEG_ERROR",
    "message": "ffmpeg exited with non-zero status",
    "details": {
      "exit_code": 1
    }
  }
}
2.6 LIVE_SESSION_STARTED

Producer: live-api или live-ingest
Consumers: live-ingest, monitoring

Idempotency key:
LIVE_SESSION_STARTED:session:{session_id}

{
  "session_id": "live_01JABC...",
  "owner_id": "42",
  "stream_key_id": "sk_123",
  "playback": {
    "output_prefix": "live/live_01JABC/hls/",
    "hls_master_key": "live/live_01JABC/hls/master.m3u8"
  },
  "started_at": "UTC ISO8601"
}
2.7 LIVE_SESSION_STOPPED

Producer: live-api или live-ingest
Consumers: live-ingest, monitoring

Idempotency key:
LIVE_SESSION_STOPPED:session:{session_id}

{
  "session_id": "live_01JABC...",
  "stopped_at": "UTC ISO8601",
  "reason": "user_request"
}
3. Processing Worker Guarantees

Worker stateless

Повтор job_id безопасен

События публикуются через outbox

PROCESSING_STARTED публикуется один раз

PROCESSING_DONE / FAILED публикуются идемпотентно


---

# 🔎 Что мы улучшили

- Убрали рассинхрон `payload` vs `data`
- Убрали `"MAJOR.MINOR"` → фиксировали `int`
- Согласовали envelope
- Зафиксировали guarantees
- Упростили формулировки
- Подготовили к реальному микросервисному разрезанию

---

