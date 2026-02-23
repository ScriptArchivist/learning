# service/paths.py
"""
Единый источник правды для storage keys и публичных URL.

Контракт (как в текущем storage_keys.py):
- original:    original/u{user_id}/v{video_id}/{uuid}{ext}
- thumbnail:   thumbnails/v{video_id}/thumb.jpg
- hls:         hls/v{video_id}/...
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import quote

from src.config import (
    DELIVERY_BASE_URL,
    HLS_PUBLIC_BASE_URL,
    HLS_PUBLIC_PATH_PREFIX,
)


# -------------------------
# Storage keys
# -------------------------

def original_path(user_id: int, video_id: int, filename: str, upload_uuid: str | None = None) -> str:
    """
    Оригинал. Пример:
      original/u1/v42/0f3d...c9.mp4
    """
    ext = os.path.splitext(filename)[1] or ""
    u = upload_uuid or str(uuid.uuid4())
    return f"original/u{user_id}/v{video_id}/{u}{ext}"


def thumbnail_path(video_id: int) -> str:
    """
    Превью:
      thumbnails/v42/thumb.jpg
    """
    return f"thumbnails/v{video_id}/thumb.jpg"


def thumbnail_dir(video_id: int) -> str:
    """
    Директория превью:
      thumbnails/v42
    """
    return f"thumbnails/v{video_id}"


def hls_dir(video_id: int) -> str:
    """
    Директория HLS:
      hls/v42
    """
    return f"hls/v{video_id}"


def hls_master(video_id: int) -> str:
    """
    Master playlist:
      hls/v42/master.m3u8
    """
    return f"{hls_dir(video_id)}/master.m3u8"


def hls_variant_playlist(video_id: int, variant: str) -> str:
    """
    Variant playlist:
      hls/v42/720p/index.m3u8
    """
    return f"{hls_dir(video_id)}/{variant}/index.m3u8"


def hls_variant_segment(video_id: int, variant: str, segment_filename: str) -> str:
    """
    Segment:
      hls/v42/720p/seg_00001.ts
    """
    return f"{hls_dir(video_id)}/{variant}/{segment_filename}"


# -------------------------
# Delivery/public URLs
# -------------------------

def delivery_url(object_key: str) -> str:
    """
    Единая сборка URL для раздачи по ключу (DELIVERY_MODE=url).

    Пример:
      DELIVERY_BASE_URL=http://localhost:8080
      object_key=hls/v42/master.m3u8
      => http://localhost:8080/hls/v42/master.m3u8
    """
    base = (DELIVERY_BASE_URL or "").rstrip("/")
    key = object_key.lstrip("/")
    # quote нужен, чтобы безопасно кодировать пробелы/юникод в именах файлов (original)
    return f"{base}/{quote(key)}"


def hls_public_master_url(video_id: int) -> str:
    """
    Public HLS URL served by nginx/CDN:
      https://domain/hls/{video_id}/master.m3u8

    Важно: у тебя nginx принимает и /hls/{id}/..., и /hls/v{id}/...
    (см. (?:v)? в regex). Поэтому тут оставляем более “чистый” вариант без v.
    """
    base = (HLS_PUBLIC_BASE_URL or "").rstrip("/")
    prefix = (HLS_PUBLIC_PATH_PREFIX or "hls").strip("/")
    return f"{base}/{prefix}/{int(video_id)}/master.m3u8"