# model/video_contract.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from model.video import (
    VideoStatus,
    Visibility,
    UserResponse,
    VideoFormatResponse,
    ProcessingTaskResponse,
)


class VideoListItemDTO(BaseModel):
    """
    Стабильный DTO для списка /videos.
    ВАЖНО: держим поля, которые реально нужны UI + стабильные ссылки/флаги.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    visibility: Visibility

    status: VideoStatus
    is_blocked: bool

    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None

    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    # --- стабильные для UI поля ---
    hls_ready: bool = False
    hls_url: Optional[str] = None

    # ссылки на ресурсы (UI не собирает руками)
    watch_url: str
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

    # share endpoints
    is_shared: bool = False
    share_url: Optional[str] = None


class VideoDetailDTO(VideoListItemDTO):
    """Полный DTO для /videos/{id} и /videos/shared/{token}."""
    owner: Optional[UserResponse] = None
    formats: List[VideoFormatResponse] = []
    processing_tasks: List[ProcessingTaskResponse] = []


class VideoListResponse(BaseModel):
    """
    FE-BE1: GET /videos возвращает строго:
      items/page/per_page/total
    """
    items: List[VideoListItemDTO]
    page: int
    per_page: int
    total: int