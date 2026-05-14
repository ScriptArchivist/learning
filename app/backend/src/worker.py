# src/worker.py
import os
import logging
import logging.config
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from src.metrics import (
    inc_video_processing,
    start_background_metrics_server,
    track_job,
)
from service.correlation import (
    get_request_id,
    get_trace_id,
    ensure_trace_id,
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
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("worker")

from db.database import SessionLocal  # noqa: E402
from service.broker import consume_forever, MAX_RETRIES  # noqa: E402
from service.ffmpeg_utils import ffprobe_metadata, make_hls, make_thumbnail  # noqa: E402
from service.processing_service import (  # noqa: E402
    complete_video_processing_with_lock,
    fail_video_processing_with_lock,
)
from service.storage_service import get_storage_provider  # noqa: E402
from src.config import VIDEO_LOCK_TTL_SECONDS  # noqa: E402
from service.video_service import try_claim_video_processing  # noqa: E402
from service.events import EventEnvelope, VideoProcessRequestedPayload  # noqa: E402
from service.paths import thumbnail_path  # noqa: E402
from service.outbox import (  # noqa: E402
    EVENT_VIDEO_PROCESS_REQUESTED,
    EVENT_VIDEO_PROCESS_FAILED,
    add_event,
)

storage = get_storage_provider()


def _safe_error_message(e: Exception, limit: int = 500) -> str:
    msg = f"{type(e).__name__}: {str(e)}"
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[:limit]


def _major_version(schema_version) -> int | None:
    if schema_version is None:
        return None
    if isinstance(schema_version, int):
        return int(schema_version)
    if isinstance(schema_version, str):
        s = schema_version.strip()
        if not s:
            return None
        try:
            return int(s.split(".", 1)[0])
        except Exception:
            return None
    return None


def _process_video_artifacts(
    *,
    video_id: int,
    orig_key: str,
    thumb_key: str,
    hls_dir_key_str: str,
    hls_master_key_str: str,
):
    """
    Единая обработка для local и S3 storage.

    Local:
      ffmpeg работает напрямую с /app/uploads.

    S3:
      original скачивается во временную директорию;
      thumbnail/HLS генерируются во временной директории;
      результат загружается обратно в S3 по тем же object keys.
    """
    orig_full = storage.resolve_local_path(orig_key)
    thumb_full = storage.resolve_local_path(thumb_key)
    hls_dir_full = storage.resolve_local_path(hls_dir_key_str)
    hls_master_full = storage.resolve_local_path(hls_master_key_str)

    # ===== Local/PVC backend =====
    if all([orig_full, thumb_full, hls_dir_full, hls_master_full]):
        if not os.path.exists(orig_full):
            raise FileNotFoundError(f"file not found: {orig_full} (key={orig_key})")

        meta = ffprobe_metadata(orig_full)
        duration = meta["duration"]
        width = meta["width"]
        height = meta["height"]
        size = os.path.getsize(orig_full)

        if os.path.exists(thumb_full) and os.path.exists(hls_master_full):
            return {
                "duration": duration,
                "width": width,
                "height": height,
                "size": size,
                "already_existed": True,
            }

        make_thumbnail(orig_full, thumb_full, at_seconds=1.0)

        if not os.path.exists(thumb_full):
            raise RuntimeError(f"thumbnail was not created: {thumb_full} (key={thumb_key})")

        make_hls(orig_full, hls_dir_full)

        if not os.path.exists(hls_master_full):
            raise RuntimeError(
                f"hls master was not created: {hls_master_full} (key={hls_master_key_str})"
            )

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "size": size,
            "already_existed": False,
        }

    # ===== S3-compatible backend =====
    with tempfile.TemporaryDirectory(prefix=f"video-{video_id}-") as tmp:
        tmp_dir = Path(tmp)

        orig_suffix = Path(orig_key).suffix or ".mp4"
        orig_tmp = tmp_dir / f"original{orig_suffix}"
        thumb_tmp = tmp_dir / "thumb.jpg"
        hls_tmp_dir = tmp_dir / "hls"

        storage.download_to_path(orig_key, str(orig_tmp))

        if not orig_tmp.exists():
            raise FileNotFoundError(f"downloaded original not found: {orig_tmp} (key={orig_key})")

        meta = ffprobe_metadata(str(orig_tmp))
        duration = meta["duration"]
        width = meta["width"]
        height = meta["height"]
        size = os.path.getsize(orig_tmp)

        if storage.file_exists(thumb_key) and storage.file_exists(hls_master_key_str):
            return {
                "duration": duration,
                "width": width,
                "height": height,
                "size": size,
                "already_existed": True,
            }

        make_thumbnail(str(orig_tmp), str(thumb_tmp), at_seconds=1.0)

        if not thumb_tmp.exists():
            raise RuntimeError(f"thumbnail was not created: {thumb_tmp} (key={thumb_key})")

        make_hls(str(orig_tmp), str(hls_tmp_dir))

        hls_master_tmp = hls_tmp_dir / "master.m3u8"
        if not hls_master_tmp.exists():
            raise RuntimeError(
                f"hls master was not created: {hls_master_tmp} (key={hls_master_key_str})"
            )

        storage.upload_file_path(
            str(thumb_tmp),
            thumb_key,
            content_type="image/jpeg",
        )
        storage.upload_dir(
            str(hls_tmp_dir),
            hls_dir_key_str,
        )

        if not storage.file_exists(thumb_key):
            raise RuntimeError(f"thumbnail was not uploaded: key={thumb_key}")

        if not storage.file_exists(hls_master_key_str):
            raise RuntimeError(f"hls master was not uploaded: key={hls_master_key_str}")

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "size": size,
            "already_existed": False,
        }


def handle(message: dict, retry_count: int) -> None:
    """
    Worker принимает только ENVELOPE (единый контракт).
    retry_count — число попаданий в RETRY queue (x-death count).
    """
    try:
        envelope = EventEnvelope.model_validate(message)
    except ValidationError:
        logger.exception("invalid EventEnvelope: message=%r", message)
        raise

    headers = {}
    if isinstance(message, dict):
        headers = message.get("__headers__") or {}

    rid = envelope.correlation_id or headers.get("x-request-id")
    tid = envelope.trace_id or headers.get("x-trace-id")
    tid = ensure_trace_id(tid)

    set_request_id(rid)
    set_trace_id(tid)

    major = _major_version(getattr(envelope, "schema_version", None))
    if major != 1:
        raise ValueError(f"unsupported schema_version={envelope.schema_version!r}")

    if envelope.event_type != EVENT_VIDEO_PROCESS_REQUESTED:
        logger.info("skip event_type=%s event_id=%s", envelope.event_type, envelope.event_id)
        return

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
    orig_key = payload.input_key
    output_prefix = payload.output_prefix
    job_id = payload.job_id
    event_id = job_id

    logger.info(
        "start video_id=%s key=%s event_id=%s retry_count=%s",
        video_id,
        orig_key,
        event_id,
        retry_count,
    )

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
        logger.info("idempotency: skip video_id=%s event_id=%s", video_id, event_id)
        inc_video_processing("processing-worker", "idempotent_skip")
        return

    inc_video_processing("processing-worker", "started")

    try:
        with track_job("processing-worker", "video.process"):
            thumb_key = thumbnail_path(video_id)
            hls_dir_key_str = output_prefix
            hls_master_key_str = f"{output_prefix}/master.m3u8"

            result = _process_video_artifacts(
                video_id=video_id,
                orig_key=orig_key,
                thumb_key=thumb_key,
                hls_dir_key_str=hls_dir_key_str,
                hls_master_key_str=hls_master_key_str,
            )

            if result["already_existed"]:
                logger.info("artifacts already exist, mark processed video_id=%s", video_id)

            complete_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                processed_at=datetime.utcnow(),
                file_size=result["size"],
                duration=result["duration"],
                width=result["width"],
                height=result["height"],
                thumbnail_path=thumb_key,
                mime_type="video/mp4",
                hls_master_key=hls_master_key_str,
                correlation_id=rid,
                trace_id=tid,
            )

            inc_video_processing("processing-worker", "completed")

            if result["already_existed"]:
                logger.info("done video_id=%s (already existed)", video_id)
            else:
                logger.info("done video_id=%s", video_id)

    except Exception as e:
        is_last_attempt = retry_count >= MAX_RETRIES

        if not is_last_attempt:
            logger.warning(
                "video_id=%s failed (attempt %s, will retry up to %s)",
                video_id,
                retry_count + 1,
                MAX_RETRIES,
            )
            raise

        logger.error("video_id=%s failed окончательно after retries=%s", video_id, retry_count)

        db = SessionLocal()
        try:
            with db.begin():
                fail_video_processing_with_lock(
                    video_id=video_id,
                    lock_token=lock_token,
                    error_message=_safe_error_message(e),
                    correlation_id=rid,
                    trace_id=tid,
                )

                add_event(
                    db,
                    event_type=EVENT_VIDEO_PROCESS_FAILED,
                    payload={"video_id": video_id, "error": _safe_error_message(e)},
                    producer="worker",
                    correlation_id=rid,
                    trace_id=tid,
                    aggregate_type="video",
                    aggregate_id=str(video_id),
                )
        finally:
            db.close()

        inc_video_processing("processing-worker", "failed")
        raise


if __name__ == "__main__":
    start_background_metrics_server(int(os.getenv("METRICS_PORT", "9100")))
    logger.info("boot: starting consumer")
    consume_forever(handle)