# src/worker.py
import os
from datetime import datetime

import logging.config
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
from db.models import VideoStatus
from service.broker import consume_forever
from service.ffmpeg_utils import ffprobe_metadata, make_hls, make_thumbnail
from service.video_service import (
    claim_video_processing,
    set_video_status_with_lock,
    set_video_processed_info,
)
from service.storage_service import get_storage_provider
from service import storage_keys
from src.config import VIDEO_LOCK_TTL_SECONDS

storage = get_storage_provider()  # ✅ единый storage


def handle(payload: dict):
    """
    payload ожидаем в формате:
      {
        "video_id": 123,
        "path": "original/u1/v123/<uuid>.mp4"   # <-- это storage key оригинала
      }

    Вариант C для HLS:
      hls/v{video_id}/master.m3u8
      hls/v{video_id}/{variant}/index.m3u8
      hls/v{video_id}/{variant}/seg_00001.ts
    """
    video_id = int(payload["video_id"])
    orig_key = payload["path"]  # storage key оригинала (НЕ локальный путь!)

    print(f"[worker] start video_id={video_id} key={orig_key}")

    # ✅ PR#2: атомарный захват обработки на уровне БД (без Redis)
    lock_token = claim_video_processing(video_id, lease_seconds=VIDEO_LOCK_TTL_SECONDS)
    if not lock_token:
        print(f"[worker] skip video_id={video_id}: already processing/processed")
        return

    # ---- формируем storage keys для артефактов ----
    thumb_key = storage_keys.thumbnail_key(video_id)
    hls_dir_key = storage_keys.hls_dir(video_id)
    hls_master_key = storage_keys.hls_master_key(video_id)  # hls/v{video_id}/master.m3u8

    # ---- получаем локальные пути (только для LocalStorage) ----
    orig_full = storage.resolve_local_path(orig_key)
    thumb_full = storage.resolve_local_path(thumb_key)
    hls_dir_full = storage.resolve_local_path(hls_dir_key)
    hls_master_full = storage.resolve_local_path(hls_master_key)

    # Если storage не локальный (S3/MinIO) — здесь позже будет download_to_tmp + upload results.
    if not all([orig_full, thumb_full, hls_dir_full, hls_master_full]):
        raise RuntimeError("Non-local storage is not supported by worker yet")

    try:
        # 1) Проверяем, что оригинал реально существует
        if not os.path.exists(orig_full):
            raise FileNotFoundError(f"file not found: {orig_full} (key={orig_key})")

        # 2) Идемпотентность по артефактам: если всё уже сделано — просто ставим READY
        if os.path.exists(thumb_full) and os.path.exists(hls_master_full):
            print(f"[worker] skip video_id={video_id}: artifacts already exist")
            set_video_status_with_lock(video_id, VideoStatus.READY, lock_token, None)
            return

        # 3) Метаданные и размер
        size = os.path.getsize(orig_full)

        meta = ffprobe_metadata(orig_full)
        duration = meta["duration"]
        width = meta["width"]
        height = meta["height"]

        # 4) Thumbnail
        make_thumbnail(orig_full, thumb_full, at_seconds=1.0)
        if not os.path.exists(thumb_full):
            raise RuntimeError(f"thumbnail was not created: {thumb_full} (key={thumb_key})")

        # 5) HLS (вариант C)
        make_hls(orig_full, hls_dir_full)
        if not os.path.exists(hls_master_full):
            raise RuntimeError(f"hls master was not created: {hls_master_full} (key={hls_master_key})")

        processed_at = datetime.utcnow()

        # 6) В БД сохраняем именно storage keys (НЕ full paths)
        set_video_processed_info(
            video_id=video_id,
            processed_at=processed_at,
            file_size=size,
            duration=duration,
            width=width,
            height=height,
            thumbnail_path=thumb_key,  # <-- ключ, а не локальный путь
            mime_type="video/mp4",
            lock_token=lock_token,     # ✅ guard по токену
        )

        set_video_status_with_lock(video_id, VideoStatus.READY, lock_token, None)

        print(
            f"[worker] done video_id={video_id}, size={size}, duration={duration}, "
            f"w={width}, h={height}, thumb_key={thumb_key}, hls_master_key={hls_master_key}"
        )

    except Exception as e:
        # ✅ guarded FAILED: только если мы всё ещё владеем lock_token
        try:
            set_video_status_with_lock(video_id, VideoStatus.FAILED, lock_token, str(e))
        except Exception:
            pass

        print(f"[worker] failed video_id={video_id}: {e}")
        raise


if __name__ == "__main__":
    print("[worker] boot: starting consumer", flush=True)
    consume_forever(handle)
