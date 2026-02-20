# src/worker.py
import os
import logging
from datetime import datetime
import logging.config

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

storage = get_storage_provider()  # ✅ единый storage
logger = logging.getLogger("worker")


def _safe_error_message(e: Exception, limit: int = 500) -> str:
    msg = f"{type(e).__name__}: {str(e)}"
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[:limit]


def _extract_envelope(message: dict) -> tuple[dict, dict, str | None, str | None]:
    """
    Возвращает:
      envelope_dict, payload_dict, correlation_id, trace_id

    Поддержка 2 форматов:
      1) envelope (event_type + payload + correlation_id/trace_id)
      2) legacy payload {"video_id":..,"path":..}
    """
    if isinstance(message, dict) and "event_type" in message and "payload" in message:
        envelope = message
        payload = envelope.get("payload") or {}
        corr = envelope.get("correlation_id")
        trace = envelope.get("trace_id")
        return envelope, payload, corr, trace

    # legacy
    envelope = {}
    payload = message if isinstance(message, dict) else {}
    return envelope, payload, None, None


def handle(message: dict):
    """
    Воркер принимает ENVELOPE:

      {
        "event_id": "...uuid...",
        "event_type": "video.process.requested",
        "schema_version": 1,
        "occurred_at": "...",
        "producer": "api",
        "correlation_id": "...",
        "trace_id": "...",
        "payload": {
          "video_id": 123,
          "path": "original/..."
        }
      }

    Также поддерживается legacy-формат: {"video_id":..,"path":..}
    """
    envelope, payload, corr_raw, trace_raw = _extract_envelope(message)

    # ===== пункт 8: correlation / trace в contextvars =====
    # Важно: ставим ДО любых логов внутри обработки, чтобы rid/tid появились в строках.
    set_request_id(corr_raw)
    set_trace_id(trace_raw)
    # ======================================================

    event_type = envelope.get("event_type")
    if event_type and event_type != "video.process.requested":
        logger.info("skip non-requested event_type=%s", event_type)
        return

    try:
        video_id = int(payload["video_id"])
        orig_key = payload["path"]
    except Exception:
        logger.error("bad message payload=%r envelope=%r", payload, envelope)
        return

    logger.info("start video_id=%s key=%s", video_id, orig_key)

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
                # ✅ пункт 8: correlation дальше
                correlation_id=corr_raw,
                trace_id=trace_raw,
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
            # ✅ пункт 8: correlation дальше
            correlation_id=corr_raw,
            trace_id=trace_raw,
        )

        logger.info("done video_id=%s", video_id)

    except Exception as e:
        # Пишем failed-событие (idempotent защита уже у тебя есть через lock/DB)
        try:
            fail_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                error_message=_safe_error_message(e),
                # ✅ пункт 8: correlation дальше
                correlation_id=corr_raw,
                trace_id=trace_raw,
            )
        except Exception:
            # если даже fail не смогли записать — всё равно логируем исходную ошибку
            logger.exception("fail_video_processing_with_lock error (video_id=%s)", video_id)

        logger.exception("failed video_id=%s", video_id)
        raise


if __name__ == "__main__":
    logger.info("boot: starting consumer")
    consume_forever(handle)