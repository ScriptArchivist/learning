# service/live_service.py
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from db.models import LiveSession
from errors import ForbiddenError, NotFoundError
from service.content_urls import live_thumb_url
from service.outbox import add_event

logger = logging.getLogger(__name__)

# settings (dev fallback)
try:
    from src.config import settings
except Exception:

    class Settings:
        storage_path = "/app/uploads"
        ORIGIN_BASE_URL = "http://localhost:8080"
        LIVE_RTMP_URL_TEMPLATE = "rtmp://localhost:1935/live/{stream_key}"
        LIVE_HLS_URL_TEMPLATE = "http://localhost:8080/live/{stream_key}/master.m3u8"

    settings = Settings()


EVENT_LIVE_SESSION_STARTED = "live.session.started"
EVENT_LIVE_SESSION_STOPPED = "live.session.stopped"
EVENT_LIVE_SESSION_EXPIRED = "live.session.expired"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _storage_base_path() -> Path:
    configured = getattr(settings, "storage_path", None)

    if configured:
        configured_path = Path(configured)
        if configured_path.is_absolute():
            return configured_path

    app_uploads = Path("/app/uploads")
    if app_uploads.exists():
        return app_uploads

    if configured:
        return Path(configured)

    return Path("uploads")


def _live_root_dir() -> Path:
    return _storage_base_path() / "live"


def _live_session_dir(stream_key: str) -> Path:
    return _live_root_dir() / stream_key


def _live_master_playlist_path(stream_key: str) -> Path:
    return _live_session_dir(stream_key) / "master.m3u8"


def _live_thumbnail_path(stream_key: str) -> Path:
    return _live_session_dir(stream_key) / "thumb.jpg"


def _build_rtmp_url(stream_key: str) -> str:
    tpl = os.getenv(
        "LIVE_RTMP_URL_TEMPLATE",
        getattr(settings, "LIVE_RTMP_URL_TEMPLATE", "rtmp://localhost:1935/live/{stream_key}"),
    )
    return tpl.format(stream_key=stream_key)


def _build_hls_url(stream_key: str) -> str:
    tpl = os.getenv(
        "LIVE_HLS_URL_TEMPLATE",
        getattr(settings, "LIVE_HLS_URL_TEMPLATE", ""),
    )
    if tpl:
        return tpl.format(stream_key=stream_key)

    origin = (getattr(settings, "ORIGIN_BASE_URL", "") or "http://localhost:8080").rstrip("/")
    return f"{origin}/live/{stream_key}/master.m3u8"


def get_live_thumbnail_url(stream_key: str | None) -> str | None:
    if not stream_key:
        return None

    thumb_path = _live_thumbnail_path(stream_key)
    if not thumb_path.exists():
        return None

    return live_thumb_url(stream_key)


def _gen_stream_key() -> str:
    return secrets.token_urlsafe(18).rstrip("=")


def _normalize_live_title(title: str | None) -> str:
    if title is None:
        return "Live"

    normalized = title.strip()
    if not normalized:
        return "Live"

    return normalized[:255]


def _safe_cleanup_stream_dir(stream_key: str) -> None:
    if not stream_key:
        logger.warning("live cleanup skipped: empty stream_key")
        return

    root = _live_root_dir().resolve()
    target = _live_session_dir(stream_key).resolve()

    try:
        target.relative_to(root)
    except Exception:
        logger.error("live cleanup blocked (path traversal?): root=%s target=%s", root, target)
        return

    if target == root:
        logger.error("live cleanup blocked: target equals root: %s", target)
        return

    if not target.exists():
        return

    try:
        shutil.rmtree(target)
        logger.info("live cleanup: removed %s", target)
    except Exception:
        logger.exception("live cleanup failed for %s", target)


def _hash_create_request(owner_id: int, stream_key: str | None, ttl_seconds: int, title: str | None) -> str:
    normalized_title = _normalize_live_title(title)
    raw = f"owner={owner_id}|stream_key={stream_key or ''}|ttl={ttl_seconds}|title={normalized_title}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _live_active_artifact_max_age_seconds() -> int:
    """
    Для active list:
    stream считаем live, только если артефакты обновлялись недавно.
    """
    try:
        return max(5, int(os.getenv("LIVE_ACTIVE_ARTIFACT_MAX_AGE_SECONDS", "20")))
    except Exception:
        return 20


def _live_disconnect_grace_seconds() -> int:
    """
    Для автоматической деактивации:
    если артефакты давно не обновлялись, started-session переводим в stopped.
    """
    try:
        return max(5, int(os.getenv("LIVE_DISCONNECT_GRACE_SECONDS", "30")))
    except Exception:
        return 30


def _latest_live_artifact_mtime(stream_key: str) -> float | None:
    """
    Берём самый свежий mtime из файлов в live/<stream_key>.
    Это надёжнее, чем смотреть только master.m3u8.
    """
    session_dir = _live_session_dir(stream_key)
    if not session_dir.exists() or not session_dir.is_dir():
        return None

    latest_mtime: float | None = None

    try:
        for entry in session_dir.iterdir():
            if not entry.is_file():
                continue
            try:
                mtime = entry.stat().st_mtime
            except FileNotFoundError:
                continue
            if latest_mtime is None or mtime > latest_mtime:
                latest_mtime = mtime
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("failed to inspect live artifacts for stream_key=%s", stream_key)
        return None

    return latest_mtime


def _artifact_age_seconds(stream_key: str | None) -> float | None:
    if not stream_key:
        return None

    latest_mtime = _latest_live_artifact_mtime(stream_key)
    if latest_mtime is None:
        return None

    return max(0.0, time.time() - latest_mtime)


def _has_recent_live_artifacts(stream_key: str | None) -> bool:
    """
    Для active list:
    - master.m3u8 должен существовать
    - файлы в каталоге должны быть свежими
    """
    if not stream_key:
        return False

    master_path = _live_master_playlist_path(stream_key)
    if not master_path.exists():
        return False

    age_seconds = _artifact_age_seconds(stream_key)
    if age_seconds is None:
        return False

    return age_seconds <= _live_active_artifact_max_age_seconds()


def _reference_timestamp_for_staleness(session: LiveSession) -> float:
    """
    Если файлов нет, fallback — started_at/created_at.
    Нужен для deactivation cleaner.
    """
    latest_mtime = _latest_live_artifact_mtime(session.stream_key)
    if latest_mtime is not None:
        return latest_mtime

    if session.started_at is not None:
        return session.started_at.timestamp()

    return session.created_at.timestamp()


def _is_stale_started_session(session: LiveSession, now_ts: float | None = None) -> bool:
    """
    Session считается stale для принудительной деактивации, если:
    - status=started
    - не stopped
    - не expired
    - и давно нет свежих артефактов
    """
    if session.status != "started":
        return False

    if session.stopped_at is not None:
        return False

    now_ts = now_ts or time.time()

    if session.expires_at is not None and session.expires_at <= _utc_now():
        return False

    ref_ts = _reference_timestamp_for_staleness(session)
    age_seconds = max(0.0, now_ts - ref_ts)

    return age_seconds > _live_disconnect_grace_seconds()


def _is_viewer_ready_session(session: LiveSession, now: datetime | None = None) -> bool:
    now = now or _utc_now()

    if not session.stream_key:
        return False

    if session.status != "started":
        return False

    if session.stopped_at is not None:
        return False

    if session.expires_at is not None and session.expires_at <= now:
        return False

    if not _has_recent_live_artifacts(session.stream_key):
        return False

    return True


def _to_active_live_item(session: LiveSession) -> dict[str, Any]:
    owner_name = None
    if getattr(session, "owner", None) is not None:
        owner_name = getattr(session.owner, "username", None)

    started_at = session.started_at or session.created_at

    return {
        "id": session.id,
        "stream_key": session.stream_key,
        "title": _normalize_live_title(getattr(session, "title", None)),
        "description": None,
        "status": session.status,
        "hls_url": _build_hls_url(session.stream_key),
        "hls_ready": True,
        "owner_name": owner_name,
        "started_at": started_at,
        "thumbnail_url": get_live_thumbnail_url(session.stream_key),
    }


def _mark_session_stopped(
    db: Session,
    session: LiveSession,
    *,
    reason: str | None = None,
    cleanup_files: bool = True,
) -> LiveSession:
    if session.status != "stopped":
        session.status = "stopped"
        session.stopped_at = _utc_now()
        db.add(session)

        add_event(
            db,
            event_type=EVENT_LIVE_SESSION_STOPPED,
            payload={
                "session_id": session.id,
                "stream_key": session.stream_key,
                "owner_id": session.owner_id,
                "stopped_at": session.stopped_at.isoformat() if session.stopped_at else None,
                "reason": reason,
            },
            producer="live-api",
            aggregate_type="live_session",
            aggregate_id=session.stream_key,
        )

        db.commit()
        db.refresh(session)

    if cleanup_files:
        _safe_cleanup_stream_dir(session.stream_key)

    return session


def create_live_session(
    db: Session,
    *,
    owner_id: int,
    stream_key: str | None,
    ttl_seconds: int,
    title: str | None,
    idempotency_key: str | None,
) -> Tuple[LiveSession, str, str, bool]:
    """
    Возвращает: (session, rtmp_url, hls_url, created_bool)
    """
    _live_root_dir().mkdir(parents=True, exist_ok=True)

    normalized_title = _normalize_live_title(title)
    req_hash = _hash_create_request(owner_id, stream_key, ttl_seconds, normalized_title)

    if idempotency_key:
        existing = db.query(LiveSession).filter(LiveSession.idempotency_key == idempotency_key).first()
        if existing:
            if existing.owner_id != owner_id:
                raise ForbiddenError("Idempotency-Key belongs to another user")
            if existing.request_hash and existing.request_hash != req_hash:
                raise Exception("Idempotency-Key conflict: request payload differs")
            return existing, _build_rtmp_url(existing.stream_key), _build_hls_url(existing.stream_key), False

    now = _utc_now()
    expires_at = now + timedelta(seconds=int(ttl_seconds))

    if stream_key:
        existing_by_key = db.query(LiveSession).filter(LiveSession.stream_key == stream_key).first()
        if existing_by_key:
            if existing_by_key.owner_id != owner_id:
                raise ForbiddenError("Access denied")
            if existing_by_key.status == "started":
                return existing_by_key, _build_rtmp_url(stream_key), _build_hls_url(stream_key), False

    last_exc: Exception | None = None
    for _ in range(5):
        key = stream_key or _gen_stream_key()
        session = LiveSession(
            owner_id=owner_id,
            stream_key=key,
            title=normalized_title,
            status="started",
            started_at=now,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            request_hash=req_hash if idempotency_key else None,
        )
        db.add(session)

        add_event(
            db,
            event_type=EVENT_LIVE_SESSION_STARTED,
            payload={
                "session_id": None,
                "stream_key": key,
                "owner_id": owner_id,
                "title": normalized_title,
                "expires_at": expires_at.isoformat(),
            },
            producer="live-api",
            aggregate_type="live_session",
            aggregate_id=key,
        )

        try:
            db.flush()
            db.commit()
            db.refresh(session)
            return session, _build_rtmp_url(key), _build_hls_url(key), True
        except Exception as e:
            db.rollback()
            last_exc = e
            if stream_key:
                break

    raise last_exc  # type: ignore[misc]


def get_live_session_by_stream_key(db: Session, *, stream_key: str, owner_id: int) -> LiveSession:
    session = db.query(LiveSession).filter(LiveSession.stream_key == stream_key).first()
    if not session:
        raise NotFoundError("Live session not found")
    if session.owner_id != owner_id:
        raise ForbiddenError("Access denied")
    return session


def get_active_live_sessions(db: Session) -> list[dict[str, Any]]:
    """
    Active list должен отражать реально идущие эфиры,
    а не просто started-session с остаточным HLS.
    """
    now = _utc_now()

    sessions = (
        db.query(LiveSession)
        .options(joinedload(LiveSession.owner))
        .filter(
            LiveSession.status == "started",
            LiveSession.stream_key.isnot(None),
            LiveSession.stopped_at.is_(None),
            or_(LiveSession.expires_at.is_(None), LiveSession.expires_at > now),
        )
        .order_by(LiveSession.started_at.desc(), LiveSession.id.desc())
        .all()
    )

    items: list[dict[str, Any]] = []
    for session in sessions:
        if not _is_viewer_ready_session(session, now=now):
            continue
        items.append(_to_active_live_item(session))

    return items


def stop_live_session(db: Session, *, session_id: int, owner_id: int) -> LiveSession:
    session = db.query(LiveSession).filter(LiveSession.id == session_id).first()
    if not session:
        raise NotFoundError("Live session not found")
    if session.owner_id != owner_id:
        raise ForbiddenError("Access denied")

    return _mark_session_stopped(
        db=db,
        session=session,
        reason="manual_stop",
        cleanup_files=True,
    )


def disconnect_live_session_by_stream_key(db: Session, *, stream_key: str) -> LiveSession | None:
    """
    Вызывается ingest-ом при disconnect publisher-а.

    Важно:
    если stream уже переподключился и артефакты снова свежие,
    callback не должен убить новую live-сессию тем же stream_key.
    """
    session = (
        db.query(LiveSession)
        .filter(LiveSession.stream_key == stream_key)
        .order_by(LiveSession.id.desc())
        .first()
    )
    if not session:
        logger.warning("disconnect ignored: live session not found for stream_key=%s", stream_key)
        return None

    if session.status in ("stopped", "expired"):
        logger.info(
            "disconnect ignored: session already inactive stream_key=%s session_id=%s status=%s",
            stream_key,
            session.id,
            session.status,
        )
        return session

    if _has_recent_live_artifacts(stream_key):
        logger.info(
            "disconnect ignored: stream has fresh artifacts, likely reconnected stream_key=%s session_id=%s",
            stream_key,
            session.id,
        )
        return session

    logger.info(
        "disconnecting live session: stream_key=%s session_id=%s owner_id=%s",
        stream_key,
        session.id,
        session.owner_id,
    )

    return _mark_session_stopped(
        db=db,
        session=session,
        reason="publisher_disconnected",
        cleanup_files=True,
    )


def deactivate_stale_live_sessions_batch(db: Session, *, limit: int = 100) -> int:
    """
    Страховочный механизм:
    если started-session повисла, а disconnect callback не дошёл,
    автоматически переводим её в stopped по признаку отсутствия активности.
    """
    now = _utc_now()

    sessions = (
        db.query(LiveSession)
        .filter(
            LiveSession.status == "started",
            LiveSession.stopped_at.is_(None),
            LiveSession.stream_key.isnot(None),
            or_(LiveSession.expires_at.is_(None), LiveSession.expires_at > now),
        )
        .order_by(LiveSession.started_at.asc(), LiveSession.id.asc())
        .limit(limit)
        .all()
    )

    stopped_count = 0
    now_ts = time.time()

    for session in sessions:
        if not _is_stale_started_session(session, now_ts=now_ts):
            continue

        logger.info(
            "auto-stopping stale live session: stream_key=%s session_id=%s owner_id=%s",
            session.stream_key,
            session.id,
            session.owner_id,
        )

        _mark_session_stopped(
            db=db,
            session=session,
            reason="stale_no_activity",
            cleanup_files=True,
        )
        stopped_count += 1

    return stopped_count


def expire_sessions_batch(db: Session, *, limit: int = 100) -> int:
    """
    TTL cleaner: started -> expired, cleanup files.
    """
    now = _utc_now()

    q = (
        db.query(LiveSession)
        .filter(
            LiveSession.status == "started",
            LiveSession.expires_at.isnot(None),
            LiveSession.expires_at <= now,
        )
        .with_for_update(skip_locked=True)
        .limit(limit)
    )

    sessions = q.all()
    if not sessions:
        return 0

    for s in sessions:
        s.status = "expired"
        db.add(s)

        add_event(
            db,
            event_type=EVENT_LIVE_SESSION_EXPIRED,
            payload={
                "session_id": s.id,
                "stream_key": s.stream_key,
                "owner_id": s.owner_id,
                "expired_at": now.isoformat(),
            },
            producer="live-api",
            aggregate_type="live_session",
            aggregate_id=s.stream_key,
        )

    db.commit()

    for s in sessions:
        _safe_cleanup_stream_dir(s.stream_key)

    return len(sessions)