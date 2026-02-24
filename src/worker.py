# src/worker.py
import os
import logging
import logging.config
from datetime import datetime

from pydantic import ValidationError

from service.paths import thumbnail_path, hls_dir, hls_master
from service.correlation import (
    get_request_id,
    get_trace_id,
    ensure_trace_id,
    set_request_id,
    set_trace_id,
)

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая сторонние libs) ---
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
logger = logging.getLogger("worker")

# ⚠️ Импорты ниже — после настройки логов (чтобы даже их import-time логи не падали)
from db.database import SessionLocal  # noqa: E402
from service.broker import consume_forever  # noqa: E402
from service.ffmpeg_utils import ffprobe_metadata, make_hls, make_thumbnail  # noqa: E402
from service.processing_service import (  # noqa: E402
    complete_video_processing_with_lock,
    fail_video_processing_with_lock,
)
from service.storage_service import get_storage_provider  # noqa: E402
from src.config import VIDEO_LOCK_TTL_SECONDS  # noqa: E402

# B2: DB-claim для идемпотентности
from service.video_service import try_claim_video_processing  # noqa: E402

# Event contract (A1)
from service.events import EventEnvelope, VideoProcessRequestedPayload  # noqa: E402
from service.outbox import EVENT_VIDEO_PROCESS_REQUESTED  # noqa: E402

storage = get_storage_provider()  # ✅ единый storage


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
        try:
            return int(s.split(".", 1)[0])
        except Exception:
            return None
    return None


def handle(message: dict):
    """
    Worker принимает ТОЛЬКО ENVELOPE (единый контракт A1).
    Идемпотентность (B2):
      - claim видео в PROCESSING атомарно в БД
      - повторная доставка -> safe no-op
    """
    # 1) Строго валидируем envelope
    try:
        envelope = EventEnvelope.model_validate(message)
    except ValidationError:
        logger.exception("invalid EventEnvelope: message=%r", message)
        raise

    # 2) correlation/trace в contextvars
    headers = {}
    if isinstance(message, dict):
        headers = message.get("__headers__") or {}

    rid = envelope.correlation_id or headers.get("x-request-id")
    tid = envelope.trace_id or headers.get("x-trace-id")
    tid = ensure_trace_id(tid)

    set_request_id(rid)
    set_trace_id(tid)

    # 3) Проверяем версию схемы (MAJOR)
    major = _major_version(getattr(envelope, "schema_version", None))
    if major != 1:
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
    event_id = str(envelope.event_id)

    logger.info("start video_id=%s key=%s event_id=%s", video_id, orig_key, event_id)

    # ---------------------------------------------------------------------
    # B2: DB-claim (идемпотентность)
    # lock_token = event_id (стабильный токен на конкретную доставку)
    # ---------------------------------------------------------------------
    lock_token = event_id
    db = SessionLocal()
    try:
        with db.begin():
            claimed = try_claim_video_processing(
                db,
                video_id=video_id,
                lock_token=lock_token,
                ttl_seconds=int(VIDEO_LOCK_TTL_SECONDS),
            )
    finally:
        db.close()

    if not claimed:
        logger.info("idempotency: skip video_id=%s event_id=%s (already processing/ready)", video_id, event_id)
        return

    try:
        thumb_key = thumbnail_path(video_id)
        hls_dir_key_str = hls_dir(video_id)
        hls_master_key_str = hls_master(video_id)

        orig_full = storage.resolve_local_path(orig_key)
        thumb_full = storage.resolve_local_path(thumb_key)
        hls_dir_full = storage.resolve_local_path(hls_dir_key_str)
        hls_master_full = storage.resolve_local_path(hls_master_key_str)

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
                hls_master_key=hls_master_key_str,
                correlation_id=rid,
                trace_id=tid,
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
            raise RuntimeError(f"hls master was not created: {hls_master_full} (key={hls_master_key_str})")

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
            hls_master_key=hls_master_key_str,
            correlation_id=rid,
            trace_id=tid,
        )

        logger.info("done video_id=%s", video_id)

    except Exception as e:
        try:
            fail_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                error_message=_safe_error_message(e),
                correlation_id=rid,
                trace_id=tid,
            )
        except Exception:
            logger.exception("fail_video_processing_with_lock error (video_id=%s)", video_id)

        logger.exception("failed video_id=%s", video_id)
        raise


if __name__ == "__main__":
    logger.info("boot: starting consumer")
    consume_forever(handle)