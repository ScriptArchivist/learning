# service/video_presenter.py
from __future__ import annotations

from pathlib import Path
from typing import Optional

from model.video_contract import VideoDetailDTO, VideoListItemDTO
from service.paths import delivery_url, hls_master, hls_dir

try:
    from src.config import settings
except ImportError:
    class Settings:
        storage_path = "/app/uploads"
        DELIVERY_MODE = "local"  # "local" | "url"
    settings = Settings()


def _is_url_mode() -> bool:
    return getattr(settings, "DELIVERY_MODE", "local") == "url"


def _full_storage_path(rel_path: str) -> str:
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return str(Path(base) / rel_path.lstrip("/"))


def _compute_hls_ready(video_id: int, status_value: str) -> bool:
    """
    Стабильное правило для UI:
      - hls_ready True только если реально есть master playlist (или url-mode).
    """
    if status_value != "ready":
        return False

    if _is_url_mode():
        return True

    master_key = hls_master(video_id)
    return Path(_full_storage_path(master_key)).exists()


def _build_hls_url(video_id: int, *, hls_ready: bool, shared_token: Optional[str] = None) -> Optional[str]:
    if not hls_ready:
        return None

    if _is_url_mode():
        return delivery_url(hls_master(video_id))

    # local-mode: отдаём API endpoint (там token-rewrite и проверка доступа)
    if shared_token:
        return f"/api/v1/videos/shared/{shared_token}/hls/master.m3u8"
    return f"/api/v1/videos/{video_id}/hls/master.m3u8"


def _share_fields(video) -> tuple[bool, Optional[str]]:
    token = getattr(video, "share_token", None)
    if not token:
        return False, None
    return True, f"/api/v1/videos/shared/{token}"


def to_list_item(video, *, shared_token: Optional[str] = None) -> VideoListItemDTO:
    """
    SQLAlchemy Video -> стабильный DTO для списка.
    shared_token задаётся только для /videos/shared/{token} (там урлы другие).
    """
    status_value = getattr(video.status, "value", str(video.status))
    visibility_value = getattr(video.visibility, "value", str(video.visibility))

    hls_ready = _compute_hls_ready(video.id, status_value=status_value)
    hls_url = _build_hls_url(video.id, hls_ready=hls_ready, shared_token=shared_token)

    is_shared, share_url = _share_fields(video)

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
    """
    Детальный DTO: list_item + owner/formats/tasks.
    """
    base = to_list_item(video, shared_token=shared_token)

    return VideoDetailDTO(
        **base.model_dump(),
        owner=getattr(video, "owner", None),
        formats=getattr(video, "formats", []) or [],
        processing_tasks=getattr(video, "processing_tasks", []) or [],
    )