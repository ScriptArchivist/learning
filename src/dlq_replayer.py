# src/dlq_replayer.py
from __future__ import annotations

import os
import logging
import logging.config
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import OutboxEvent, OutboxStatus


logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("dlq-replayer")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


LIMIT = _env_int("DLQ_REPLAY_LIMIT", 200)
RESET_ATTEMPTS = os.getenv("DLQ_RESET_ATTEMPTS", "1").strip() == "1"


def replay_failed(db: Session, limit: int) -> int:
    """
    “Разморозка” FAILED → NEW (available_at=now, locked_at=None, last_error остаётся для истории).
    Это НЕ публикует сразу — публикацией занимается outbox-publisher.
    """
    now = datetime.utcnow()

    ids = list(
        db.execute(
            select(OutboxEvent.id)
            .where(OutboxEvent.status == OutboxStatus.FAILED.value)
            .order_by(OutboxEvent.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
    )

    if not ids:
        return 0

    values = {
        "status": OutboxStatus.NEW.value,
        "available_at": now,
        "locked_at": None,
    }
    if RESET_ATTEMPTS:
        values["attempts"] = 0

    db.execute(update(OutboxEvent).where(OutboxEvent.id.in_(ids)).values(**values))
    return len(ids)


def main() -> None:
    logger.info("boot: dlq-replayer limit=%s reset_attempts=%s", LIMIT, RESET_ATTEMPTS)

    db = SessionLocal()
    try:
        with db.begin():
            n = replay_failed(db, LIMIT)
        logger.info("replayed=%s", n)
    finally:
        db.close()


if __name__ == "__main__":
    main()