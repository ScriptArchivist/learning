# src/worker.py
import os
from datetime import datetime

import logging.config
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


def _safe_error_message(e: Exception, limit: int = 500) -> str:
    msg = f"{type(e).__name__}: {str(e)}"
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[:limit]


def handle(message: dict):
    """
    Теперь воркер принимает ENVELOPE:

      {
        "event_id": "...uuid...",
        "event_type": "video.process.requested",
        "schema_version": 1,
        "occurred_at": "...",
        "producer": "api",
        "correlation_id": null,
        "trace_id": null,
        "payload": {
          "video_id": 123,
          "path": "original/..."
        }
      }

    (на всякий случай поддерживаем старый формат: {"video_id":..,"path":..})
    """
    # backwards compatible
    if "event_type" in message and "payload" in message:
        event_type = message.get("event_type")
        payload = message.get("payload") or {}
    else:
        event_type = None
        payload = message

    if event_type and event_type != "video.process.requested":
        print(f"[worker] skip non-requested event_type={event_type}")
        return

    video_id = int(payload["video_id"])
    orig_key = payload["path"]

    # можно потом использовать для логов (пункт 8)
    correlation_id = (message.get("correlation_id") if isinstance(message, dict) else None) or "-"
    trace_id = (message.get("trace_id") if isinstance(message, dict) else None) or "-"

    print(f"[worker] start video_id={video_id} key={orig_key} corr={correlation_id} trace={trace_id}")

    lock_token = claim_video_processing(video_id, lease_seconds=VIDEO_LOCK_TTL_SECONDS)
    if not lock_token:
        print(f"[worker] skip video_id={video_id}: already processing/processed")
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

        if os.path.exists(thumb_full) and os.path.exists(hls_master_full):
            print(f"[worker] skip video_id={video_id}: artifacts already exist")

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
            )
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
        )

        print(f"[worker] done video_id={video_id} corr={correlation_id} trace={trace_id}")

    except Exception as e:
        try:
            fail_video_processing_with_lock(
                video_id=video_id,
                lock_token=lock_token,
                error_message=str(e),
            )
        except Exception:
            pass

        print(f"[worker] failed video_id={video_id} corr={correlation_id} trace={trace_id}: {e}")
        raise


if __name__ == "__main__":
    print("[worker] boot: starting consumer", flush=True)
    consume_forever(handle)
