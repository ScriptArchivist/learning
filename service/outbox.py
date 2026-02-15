# service/outbox.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import OutboxEvent, OutboxStatus


EVENT_VIDEO_PROCESS_REQUESTED = "video.process.requested"


def add_event(
    db: Session,
    *,
    event_type: str,
    payload: dict[str, Any],
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    available_at: datetime | None = None,
) -> OutboxEvent:
    evt = OutboxEvent(
        event_type=event_type,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        available_at=available_at or datetime.utcnow(),
        status=OutboxStatus.PENDING.value,
        attempts=0,
    )
    db.add(evt)
    return evt


def fetch_pending_batch(db: Session, *, limit: int) -> list[OutboxEvent]:
    """
    Postgres: FOR UPDATE SKIP LOCKED позволяет безопасно запускать несколько publisher'ов.
    """
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status == OutboxStatus.PENDING.value,
            OutboxEvent.available_at <= datetime.utcnow(),
        )
        .order_by(OutboxEvent.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def mark_published(db: Session, event_id: int) -> None:
    db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(status=OutboxStatus.PUBLISHED.value, published_at=datetime.utcnow(), last_error=None)
    )


def mark_failed_retry(db: Session, event_id: int, err: str, attempts: int) -> None:
    # простой backoff: 2^attempts секунд, но не более 5 минут
    delay = min(300, 2 ** min(attempts, 8))
    db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(
            attempts=attempts,
            last_error=err[:2000],
            available_at=datetime.utcnow() + timedelta(seconds=delay),
        )
    )
