# service/video_presenter.py
from __future__ import annotations

from typing import Optional

from model.video_contract import VideoDetailDTO, VideoListItemDTO
from service.paths import hls_public_master_url

try:
    from src.config import settings
except ImportError:
    class Settings:
        DELIVERY_MODE = "url"
    settings = Settings()


def _is_url_mode() -> bool:
    # В “правильной” архитектуре playback всегда через origin/url-mode
    return getattr(settings, "DELIVERY_MODE", "url") == "url"


def _compute_hls_ready(status_value: str) -> bool:
    # Единственный источник правды для готовности — доменный статус.
    return status_value == "ready"


def _build_hls_url(video_id: int, *, hls_ready: bool) -> Optional[str]:
    if not hls_ready:
        return None

    # В правильной схеме всегда публичная раздача через origin
    # (/hls/v{id}/master.m3u8)
    return hls_public_master_url(video_id)


def _share_fields(video) -> tuple[bool, Optional[str]]:
    token = getattr(video, "share_token", None)
    if not token:
        return False, None
    return True, f"/api/v1/videos/shared/{token}"


def to_list_item(video, *, shared_token: Optional[str] = None) -> VideoListItemDTO:
    status_value = getattr(video.status, "value", str(video.status))
    visibility_value = getattr(video.visibility, "value", str(video.visibility))

    hls_ready = _compute_hls_ready(status_value=status_value)
    hls_url = _build_hls_url(video.id, hls_ready=hls_ready)

    is_shared, share_url = _share_fields(video)

    # Эти url'ы в video-api могут быть неиспользуемы (Flutter ходит только в playback),
    # но оставим стабильную схему DTO.
    if shared_token:
        watch_url = f"/api/v1/videos/shared/{shared_token}/watch"
        file_url = f"/api/v1/videos/shared/{shared_token}/file"
        thumbnail_url = f"/api/v1/videos/shared/{shared_token}/thumbnail"
    else:
        watch_url = f"/api/v1/videos/{video.id}/watch"
        file_url = f"/api/v1/videos/{video.id}/file"
        thumbnail_url = f"/api/v1/videos/{video.id}/thumbnail"

    return VideoListItemDTO(
        id=video.id,
        owner_id=video.owner_id,
        title=video.title,
        description=video.description,
        visibility=visibility_value,
        status=status_value,
        is_blocked=bool(video.is_blocked),
        duration=video.duration,
        width=video.width,
        height=video.height,
        size_bytes=video.size_bytes,
        mime_type=video.mime_type,
        uploaded_at=video.uploaded_at,
        processed_at=video.processed_at,
        error_message=video.error_message,
        hls_ready=hls_ready,
        hls_url=hls_url,
        watch_url=watch_url,
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        is_shared=is_shared,
        share_url=share_url,
    )


def to_detail(video, *, shared_token: Optional[str] = None) -> VideoDetailDTO:
    base = to_list_item(video, shared_token=shared_token)
    return VideoDetailDTO(
        **base.model_dump(),
        owner=getattr(video, "owner", None),
        formats=getattr(video, "formats", []) or [],
        processing_tasks=getattr(video, "processing_tasks", []) or [],
    )