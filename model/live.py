# model/live.py
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


LiveSessionStatus = Literal["created", "started", "stopped", "expired", "error"]


class LiveSessionDTO(BaseModel):
    id: int
    owner_id: int
    stream_key: str
    title: str
    status: LiveSessionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    error: Optional[str] = None
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


class LiveSessionActiveItemDTO(BaseModel):
    id: Optional[int] = None
    stream_key: str
    title: str
    description: Optional[str] = None
    status: str
    hls_url: Optional[str] = None
    hls_ready: bool
    owner_name: Optional[str] = None
    started_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


class LiveSessionCreateRequest(BaseModel):
    stream_key: Optional[str] = None
    ttl_seconds: int = Field(default=1800, ge=60, le=24 * 3600)
    title: Optional[str] = Field(default=None, max_length=255)


class LiveSessionCreateResponse(BaseModel):
    session: LiveSessionDTO
    rtmp_url: str
    hls_url: str
    thumbnail_url: Optional[str] = None