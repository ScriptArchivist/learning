# service/live_service.py
from __future__ import annotations

import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from sqlalchemy.orm import Session

from db.models import LiveSession
from errors import ForbiddenError, NotFoundError

# settings (dev fallback)
try:
    from src.config import settings
except Exception:

    class Settings:
        storage_path = "/app/uploads"
        ORIGIN_BASE_URL = "http://localhost:8080"  # nginx/origin
        # ✅ правильные дефолты для тестов
        LIVE_RTMP_URL_TEMPLATE = "rtmp://localhost:1935/live/{stream_key}"
        LIVE_HLS_URL_TEMPLATE = "http://localhost:8080/live/{stream_key}/master.m3u8"

    settings = Settings()


def _live_root_dir() -> Path:
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return Path(base) / "live"


def _live_session_dir(stream_key: str) -> Path:
    return _live_root_dir() / stream_key


def _build_rtmp_url(stream_key: str) -> str:
    # ✅ дефолт с портом 1935
    tpl = os.getenv(
        "LIVE_RTMP_URL_TEMPLATE",
        getattr(settings, "LIVE_RTMP_URL_TEMPLATE", "rtmp://localhost:1935/live/{stream_key}"),
    )
    return tpl.format(stream_key=stream_key)


def _build_hls_url(stream_key: str) -> str:
    # ✅ дефолт на master.m3u8
    tpl = os.getenv(
        "LIVE_HLS_URL_TEMPLATE",
        getattr(settings, "LIVE_HLS_URL_TEMPLATE", ""),
    )
    if tpl:
        return tpl.format(stream_key=stream_key)

    origin = (getattr(settings, "ORIGIN_BASE_URL", "") or "http://localhost:8080").rstrip("/")
    return f"{origin}/live/{stream_key}/master.m3u8"


def _gen_stream_key() -> str:
    return secrets.token_urlsafe(18).rstrip("=")


def create_live_session(db: Session, owner_id: int) -> Tuple[LiveSession, str, str]:
    _live_root_dir().mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for _ in range(5):
        stream_key = _gen_stream_key()
        session = LiveSession(
            owner_id=owner_id,
            stream_key=stream_key,
            status="created",
        )
        db.add(session)
        try:
            db.commit()
            db.refresh(session)
            return session, _build_rtmp_url(stream_key), _build_hls_url(stream_key)
        except Exception as e:
            db.rollback()
            last_exc = e

    raise last_exc  # type: ignore[misc]


def get_live_session(db: Session, session_id: int, owner_id: int) -> LiveSession:
    session = db.query(LiveSession).filter(LiveSession.id == session_id).first()
    if not session:
        raise NotFoundError("Live session not found")
    if session.owner_id != owner_id:
        raise ForbiddenError("Access denied")
    return session


def stop_live_session(db: Session, session_id: int, owner_id: int) -> LiveSession:
    session = get_live_session(db=db, session_id=session_id, owner_id=owner_id)

    if session.status != "stopped":
        session.status = "stopped"
        session.stopped_at = datetime.now(timezone.utc)
        db.add(session)
        db.commit()
        db.refresh(session)

    # TASK C3: cleanup после stop
    shutil.rmtree(_live_session_dir(session.stream_key), ignore_errors=True)
    return session