# service/storage_keys.py
"""
Единый источник правды для storage keys.

Зачем:
- все сервисы (API, worker, будущие микросервисы) должны совпадать по путям
- легко перейти с Local FS на S3/MinIO без переписывания логики
"""

from __future__ import annotations

import os
import uuid


def original_key(user_id: int, video_id: int, filename: str, upload_uuid: str | None = None) -> str:
    """
    Оригинал. Пример:
      original/u1/v42/0f3d...c9.mp4
    """
    ext = os.path.splitext(filename)[1] or ""
    u = upload_uuid or str(uuid.uuid4())
    return f"original/u{user_id}/v{video_id}/{u}{ext}"


def thumbnail_key(video_id: int) -> str:
    """
    Превью:
      thumbnails/v42/thumb.jpg
    """
    return f"thumbnails/v{video_id}/thumb.jpg"


def hls_dir(video_id: int) -> str:
    """
    Директория HLS:
      hls/v42
    """
    return f"hls/v{video_id}"


def hls_master_key(video_id: int) -> str:
    """
    Master playlist:
      hls/v42/master.m3u8
    """
    return f"{hls_dir(video_id)}/master.m3u8"


def hls_variant_playlist_key(video_id: int, variant: str) -> str:
    """
    Variant playlist:
      hls/v42/720p/index.m3u8
    """
    return f"{hls_dir(video_id)}/{variant}/index.m3u8"


def hls_variant_segment_key(video_id: int, variant: str, segment_filename: str) -> str:
    """
    Segment:
      hls/v42/720p/seg_00001.ts
    """
    return f"{hls_dir(video_id)}/{variant}/{segment_filename}"
