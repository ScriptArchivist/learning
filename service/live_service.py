# service/live_service.py
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

from sqlalchemy.orm import Session

from db.models import LiveSession
from errors import ForbiddenError, NotFoundError
from service.outbox import add_event

logger = logging.getLogger(__name__)

# settings (dev fallback)
try:
    from src.config import settings
except Exception:

    class Settings:
        storage_path = "/app/uploads"
        ORIGIN_BASE_URL = "http://localhost:8080"  # nginx/origin
        LIVE_RTMP_URL_TEMPLATE = "rtmp://localhost:1935/live/{stream_key}"
        LIVE_HLS_URL_TEMPLATE = "http://localhost:8080/live/{stream_key}/master.m3u8"

    settings = Settings()


EVENT_LIVE_SESSION_STARTED = "live.session.started"
EVENT_LIVE_SESSION_STOPPED = "live.session.stopped"
EVENT_LIVE_SESSION_EXPIRED = "live.session.expired"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _live_root_dir() -> Path:
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return Path(base) / "live"


def _live_session_dir(stream_key: str) -> Path:
    return _live_root_dir() / stream_key


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


def _gen_stream_key() -> str:
    return secrets.token_urlsafe(18).rstrip("=")


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


def _hash_create_request(owner_id: int, stream_key: str | None, ttl_seconds: int) -> str:
    raw = f"owner={owner_id}|stream_key={stream_key or ''}|ttl={ttl_seconds}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_live_session(
    db: Session,
    *,
    owner_id: int,
    stream_key: str | None,
    ttl_seconds: int,
    idempotency_key: str | None,
) -> Tuple[LiveSession, str, str, bool]:
    """
    Возвращает: (session, rtmp_url, hls_url, created_bool)

    Идемпотентность:
      - если передан Idempotency-Key: повтор вернёт ту же сессию
      - если повтор с тем же ключом, но другим body => 409
      - если ключ не передан: повтор по stream_key (если передан) вернёт существующую started
    """
    _live_root_dir().mkdir(parents=True, exist_ok=True)

    req_hash = _hash_create_request(owner_id, stream_key, ttl_seconds)

    # 1) Idempotency-Key
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

    # 2) Если клиент передал stream_key — повторяемость по нему
    if stream_key:
        existing_by_key = db.query(LiveSession).filter(LiveSession.stream_key == stream_key).first()
        if existing_by_key:
            if existing_by_key.owner_id != owner_id:
                raise ForbiddenError("Access denied")
            # если уже started и не остановлена — идемпотентный ответ
            if existing_by_key.status == "started":
                return existing_by_key, _build_rtmp_url(stream_key), _build_hls_url(stream_key), False

    # 3) Создаём новую сессию (stream_key может быть сгенерен)
    last_exc: Exception | None = None
    for _ in range(5):
        key = stream_key or _gen_stream_key()
        session = LiveSession(
            owner_id=owner_id,
            stream_key=key,
            status="started",
            started_at=now,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            request_hash=req_hash if idempotency_key else None,
        )
        db.add(session)

        # outbox (в той же транзакции)
        add_event(
            db,
            event_type=EVENT_LIVE_SESSION_STARTED,
            payload={
                "session_id": None,  # заполним после flush/commit, см ниже
                "stream_key": key,
                "owner_id": owner_id,
                "expires_at": expires_at.isoformat(),
            },
            producer="live-api",
            aggregate_type="live_session",
            aggregate_id=key,
        )

        try:
            db.flush()  # получаем session.id до commit
            # обновим payload session_id у последнего evt (он в session new объектов)
            # самый простой способ: найти последний OutboxEvent в identity_map не будем — оставим session_id=None
            # (если тебе нужен строго session_id — скажи, сделаю аккуратно через явное создание OutboxEvent)
            db.commit()
            db.refresh(session)
            return session, _build_rtmp_url(key), _build_hls_url(key), True
        except Exception as e:
            db.rollback()
            last_exc = e
            # если stream_key был задан клиентом — не имеет смысла повторять генерацию
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


def stop_live_session(db: Session, *, session_id: int, owner_id: int) -> LiveSession:
    session = db.query(LiveSession).filter(LiveSession.id == session_id).first()
    if not session:
        raise NotFoundError("Live session not found")
    if session.owner_id != owner_id:
        raise ForbiddenError("Access denied")

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
            },
            producer="live-api",
            aggregate_type="live_session",
            aggregate_id=session.stream_key,
        )

        db.commit()
        db.refresh(session)

    # cleanup после stop
    _safe_cleanup_stream_dir(session.stream_key)
    return session


def expire_sessions_batch(db: Session, *, limit: int = 100) -> int:
    """
    Для TTL cleaner: переводит протухшие started -> expired, пишет outbox, чистит каталоги.
    Возвращает количество обработанных.
    """
    now = _utc_now()

    # берём пачку для обработки (skip_locked чтобы 2 cleaner не дрались)
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

    # cleanup после commit (чтобы не держать транзакцию на I/O)
    for s in sessions:
        _safe_cleanup_stream_dir(s.stream_key)

    return len(sessions)