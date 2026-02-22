# src/worker.py
import os
import json
import logging
import logging.config
from datetime import datetime

from pydantic import ValidationError

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая ffmpeg_utils) ---
from service.correlation import (
    get_request_id,
    get_trace_id,
    set_request_id,
    set_trace_id,
)

_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)
# ---------------------------------------------------------------------------------------------

# Подхватываем формат логов из ini (у тебя там rid=%(request_id)s ...)
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)

from service.broker import consume_forever
from service.ffmpeg_utils import ffprobe_metadata, make_hls, make_thumbnail
from service.processing_service import (
    claim_video_processing,
    complete_video_processing_with_lock,
    fail_video_processing_with_lock,
)
from service.storage_service import get_storage_provider
from service import storage_keys
from src.config import VIDEO_LOCK_TTL_SECONDS

# Event contract (A1)
from service.events import EventEnvelope, VideoProcessRequestedPayload

# Если у тебя эти константы лежат в service/outbox.py — импортируй оттуда
from service.outbox import EVENT_VIDEO_PROCESS_REQUESTED

storage = get_storage_provider()  # ✅ единый storage
logger = logging.getLogger("worker")


def _safe_error_message(e: Exception, limit: int = 500) -> str:
    msg = f"{type(e).__name__}: {str(e)}"
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[:limit]


def _major_version(schema_version) -> int | None:
    """
    Поддержка на время перехода:
    - schema_version может быть "1.0" (строка) или 1 (int)
    Возвращает MAJOR или None если распарсить нельзя.
    """
    if schema_version is None:
        return None
    if isinstance(schema_version, int):
        return schema_version
    if isinstance(schema_version, str):
        s = schema_version.strip()
        if not s:
            return None
        # "1" или "1.0"
        try:
            return int(s.split(".", 1)[0])
        except Exception:
            return None
    return None


def handle(message: dict):
    """
    Worker принимает ТОЛЬКО ENVELOPE (единый контракт A1).

    Пример:
      {
        "event_id": "...uuid...",
        "event_type": "video.process.requested",
        "schema_version": "1.0",
        "occurred_at": "...",
        "producer": "api",
        "correlation_id": "...",
        "trace_id": "...",
        "payload": {
          "video_id": 123,
          "path": "original/..."
        }
      }
    """

    # 1) Строго валидируем envelope
    try:
        envelope = EventEnvelope.model_validate(message)
    except ValidationError:
        logger.exception("invalid EventEnvelope: message=%r", message)
        raise

    # 2) Ставим correlation/trace в contextvars ДО любых логов обработки
    set_request_id(envelope.correlation_id)
    set_trace_id(envelope.trace_id)

    # 3) Проверяем версию схемы (MAJOR)
    major = _major_version(getattr(envelope, "schema_version", None))
    if major != 1:
        # Это осознанно: лучше отправить в retry/DLQ, чем “молча” обработать неправильно
        raise ValueError(f"unsupported schema_version={envelope.schema_version!r}")

    # 4) Обрабатываем только нужный event_type
    if envelope.event_type != EVENT_VIDEO_PROCESS_REQUESTED:
        logger.info("skip event_type=%s event_id=%s", envelope.event_type, envelope.event_id)
        return

    # 5) Строго валидируем payload по схеме
    try:
        payload = VideoProcessRequestedPayload.model_validate(envelope.payload)
    except ValidationError:
        logger.exception(
            "invalid payload for event_type=%s event_id=%s payload=%r",
            envelope.event_type,
            envelope.event_id,
            envelope.payload,
        )
        raise

    video_id = int(payload.video_id)
    orig_key = payload.path

    logger.info("start video_id=%s key=%s event_id=%s", video_id, orig_key, envelope.event_id)

    lock_token = claim_video_processing(video_id, lease_seconds=VIDEO_LOCK_TTL_SECONDS)
    if not lock_token:
        logger.info("skip video_id=%s: already processing/processed", video_id)
        return

    try:
        thumb_key = storage_keys.thumbnail_key(video_id)
        hls_dir_key = storage_keys.hls_dir(video_id)
        hls_master_key = storage_keys.hls_master_key(video_id)

        orig_full = storage.resolve_local_path(orig_key)
        thumb_full = storage.resolve_local_path(thumb_key)
        hls_dir_full = storage.resolve_local_path(hls_dir_key)
        hls_master_full = storage.resolve_local_path(hls_master_key)

        if not all([orig_full, thumb_full, hls_dir_full, hls_master_full]):
            raise RuntimeError("Non-local storage is not supported by worker yet")

        if not os.path.exists(orig_full):
            raise FileNotFoundError(f"file not found: {orig_full} (key={orig_key})")

        # если артефакты уже есть — просто фиксируем processed
        if os.path.exists(thumb_full) and os.path.exists(hls_master_full):
            logger.info("artifacts already exist, mark processed video_id=%s", video_id)

            complete_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                processed_at=datetime.utcnow(),
                file_size=os.path.getsize(orig_full),
                duration=None,
                width=None,
                height=None,
                thumbnail_path=thumb_key,
                mime_type="video/mp4",
                hls_master_key=hls_master_key,
                correlation_id=envelope.correlation_id,
                trace_id=envelope.trace_id,
            )
            logger.info("done video_id=%s (already existed)", video_id)
            return

        size = os.path.getsize(orig_full)

        meta = ffprobe_metadata(orig_full)
        duration = meta["duration"]
        width = meta["width"]
        height = meta["height"]

        make_thumbnail(orig_full, thumb_full, at_seconds=1.0)
        if not os.path.exists(thumb_full):
            raise RuntimeError(f"thumbnail was not created: {thumb_full} (key={thumb_key})")

        make_hls(orig_full, hls_dir_full)
        if not os.path.exists(hls_master_full):
            raise RuntimeError(f"hls master was not created: {hls_master_full} (key={hls_master_key})")

        processed_at = datetime.utcnow()

        complete_video_processing_with_lock(
            video_id=video_id,
            lock_token=lock_token,
            processed_at=processed_at,
            file_size=size,
            duration=duration,
            width=width,
            height=height,
            thumbnail_path=thumb_key,
            mime_type="video/mp4",
            hls_master_key=hls_master_key,
            correlation_id=envelope.correlation_id,
            trace_id=envelope.trace_id,
        )

        logger.info("done video_id=%s", video_id)

    except Exception as e:
        # Пишем failed-событие (idempotent защита уже у тебя есть через lock/DB)
        try:
            fail_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                error_message=_safe_error_message(e),
                correlation_id=envelope.correlation_id,
                trace_id=envelope.trace_id,
            )
        except Exception:
            logger.exception("fail_video_processing_with_lock error (video_id=%s)", video_id)

        logger.exception("failed video_id=%s", video_id)
        raise


if __name__ == "__main__":
    logger.info("boot: starting consumer")
    consume_forever(handle)