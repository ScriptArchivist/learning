# service/events.py
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# Единый номер схемы для envelope/payload текущего поколения (MAJOR.MINOR)
SCHEMA_VERSION = "1.0"


class EventEnvelope(BaseModel):
    """
    Единый контракт события (envelope).

    ВАЖНО:
      - schema_version: "MAJOR.MINOR"
      - occurred_at: UTC
      - payload: зависит от event_type и schema_version
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    schema_version: str = SCHEMA_VERSION
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    producer: str
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    payload: Dict[str, Any]


# -------------------------
# Payload schemas (v1.x)
# -------------------------

class VideoProcessRequestedPayload(BaseModel):
    """
    Job envelope для processing-worker.
    """
    job_id: str
    video_id: int
    input_key: str
    output_prefix: str
    attempt: int = 1


class VideoProcessCompletedPayload(BaseModel):
    """
    video.process.completed (v1.0)

    Минимальный сигнал о завершении.
    Все подробные метаданные уже лежат в БД (duration/width/height/...).
    В v1.1 можно добавить result/metrics без breaking changes.
    """
    video_id: int


class VideoProcessFailedPayload(BaseModel):
    """
    video.process.failed (v1.0)
    """
    video_id: int
    error: str