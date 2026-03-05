from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import get_db_write
from db.models import LiveSession
from service.live_service import _safe_cleanup_stream_dir  # noqa: SLF001

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("live_ttl_cleaner")


def _interval_seconds() -> int:
    return max(5, int(os.getenv("LIVE_TTL_INTERVAL_SECONDS", "10")))


def _batch_size() -> int:
    return max(1, int(os.getenv("LIVE_TTL_BATCH_SIZE", "100")))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def expire_once(db: Session) -> int:
    """
    Ищем live_sessions, у которых истёк expires_at, и:
      1) переводим статус -> expired (если ещё не stopped/expired)
      2) чистим /app/uploads/live/<stream_key>
    """
    now = _utc_now()

    # Берём только активные сессии, у которых истёк expires_at
    stmt = (
        select(LiveSession)
        .where(
            LiveSession.expires_at.is_not(None),
            LiveSession.expires_at <= now,
            LiveSession.status.in_(("created", "started")),
        )
        .order_by(LiveSession.expires_at.asc())
        .limit(_batch_size())
        .with_for_update(skip_locked=True)
    )

    sessions = list(db.execute(stmt).scalars().all())
    if not sessions:
        return 0

    expired_count = 0
    for s in sessions:
        stream_key = s.stream_key

        # 1) mark expired in DB
        s.status = "expired"
        db.add(s)
        expired_count += 1

        # 2) cleanup files
        try:
            _safe_cleanup_stream_dir(stream_key)
            logger.info("expired cleanup done: stream_key=%s session_id=%s", stream_key, s.id)
        except Exception:
            logger.exception("expired cleanup failed: stream_key=%s session_id=%s", stream_key, s.id)

    db.commit()
    return expired_count


def main() -> None:
    logger.info(
        "live TTL cleaner started: interval=%ss batch=%s db=%s",
        _interval_seconds(),
        _batch_size(),
        os.getenv("DATABASE_URL") or os.getenv("DATABASE_WRITE_URL") or "unknown",
    )

    while True:
        try:
            # db write session
            db = next(get_db_write())
            try:
                n = expire_once(db)
                if n:
                    logger.info("expired sessions: %s", n)
            finally:
                db.close()
        except Exception:
            logger.exception("live TTL cleaner loop failed")

        time.sleep(_interval_seconds())


if __name__ == "__main__":
    main()