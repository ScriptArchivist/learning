# model/live.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel


LiveSessionStatus = Literal["created", "started", "stopped", "error"]


class LiveSessionDTO(BaseModel):
    id: int
    owner_id: int
    stream_key: str
    status: LiveSessionStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class LiveSessionCreateResponse(BaseModel):
    session: LiveSessionDTO
    rtmp_url: str
    hls_url: str