# service/paths.py
"""
Единый источник правды для storage keys и публичных URL.

Контракт:
- original:    original/u{user_id}/v{video_id}/{uuid}{ext}
- thumbnail:   thumbnails/v{video_id}/thumb.jpg
- hls:         hls/v{video_id}/...
Публичный HLS URL (канон):
- /hls/v{video_id}/master.m3u8
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import quote

try:
    from src.config import DELIVERY_BASE_URL, HLS_PUBLIC_BASE_URL, HLS_PUBLIC_PATH_PREFIX
except Exception:
    DELIVERY_BASE_URL = "http://origin"
    HLS_PUBLIC_BASE_URL = "http://localhost:8080"
    HLS_PUBLIC_PATH_PREFIX = "hls"


# -------------------------
# Storage keys
# -------------------------

def original_path(user_id: int, video_id: int, filename: str, upload_uuid: str | None = None) -> str:
    ext = os.path.splitext(filename)[1] or ""
    u = upload_uuid or str(uuid.uuid4())
    return f"original/u{user_id}/v{video_id}/{u}{ext}"


def thumbnail_path(video_id: int) -> str:
    return f"thumbnails/v{video_id}/thumb.jpg"


def thumbnail_dir(video_id: int) -> str:
    return f"thumbnails/v{video_id}"


def hls_dir(video_id: int) -> str:
    return f"hls/v{video_id}"


def hls_master(video_id: int) -> str:
    return f"{hls_dir(video_id)}/master.m3u8"


def hls_variant_playlist(video_id: int, variant: str) -> str:
    return f"{hls_dir(video_id)}/{variant}/index.m3u8"


def hls_variant_segment(video_id: int, variant: str, segment_filename: str) -> str:
    return f"{hls_dir(video_id)}/{variant}/{segment_filename}"


# -------------------------
# Delivery/public URLs
# -------------------------

def delivery_url(object_key: str) -> str:
    """
    URL для раздачи по ключу (DELIVERY_MODE=url).
    Пример:
      DELIVERY_BASE_URL=http://localhost:8080
      object_key=hls/v42/master.m3u8
      => http://localhost:8080/hls/v42/master.m3u8
    """
    base = (DELIVERY_BASE_URL or "").rstrip("/")
    key = object_key.lstrip("/")
    return f"{base}/{quote(key)}"


def hls_public_master_url(video_id: int) -> str:
    """
    Канонический public HLS URL (served by nginx/CDN):
      {HLS_PUBLIC_BASE_URL}/{HLS_PUBLIC_PATH_PREFIX}/v{video_id}/master.m3u8

    Например:
      http://localhost:8080/hls/v1/master.m3u8
    """
    base = (HLS_PUBLIC_BASE_URL or "").rstrip("/")
    prefix = (HLS_PUBLIC_PATH_PREFIX or "hls").strip("/")
    return f"{base}/{prefix}/v{int(video_id)}/master.m3u8"