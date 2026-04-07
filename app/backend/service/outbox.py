# service/outbox.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import OutboxEvent, OutboxStatus
from service.events import EventEnvelope, SCHEMA_VERSION
from service.correlation import ensure_request_id, ensure_trace_id


EVENT_VIDEO_PROCESS_COMPLETED = "video.process.completed"
EVENT_VIDEO_PROCESS_FAILED = "video.process.failed"
EVENT_VIDEO_PROCESS_REQUESTED = "video.process.requested"

MAX_ATTEMPTS = 10
LOCK_TTL_SECONDS = 300  # 5 минут


def _utc_now():
    return datetime.utcnow()


# ------------------------------------------------------------
# ADD EVENT
# ------------------------------------------------------------

def add_event(
    db: Session,
    *,
    event_type: str,
    payload: dict[str, Any],
    producer: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    schema_version: str | None = None,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    available_at: datetime | None = None,
) -> OutboxEvent:

    correlation_id = ensure_request_id(correlation_id)
    trace_id = ensure_trace_id(trace_id)

    envelope = EventEnvelope(
        event_type=event_type,
        schema_version=schema_version or SCHEMA_VERSION,
        producer=producer,
        correlation_id=correlation_id,
        trace_id=trace_id,
        payload=payload,
    )

    evt = OutboxEvent(
        event_type=event_type,
        payload=envelope.model_dump(mode="json"),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        available_at=available_at or _utc_now(),
        status=OutboxStatus.NEW.value,
        attempts=0,
    )

    db.add(evt)
    return evt


# ------------------------------------------------------------
# CLAIM BATCH
# ------------------------------------------------------------

def fetch_pending_batch(db: Session, *, limit: int) -> list[OutboxEvent]:
    """
    1) Берём NEW
    2) Или протухшие PROCESSING (locked_at старше TTL)
    3) Сразу переводим в PROCESSING + locked_at
    """

    now = _utc_now()
    lock_expired = now - timedelta(seconds=LOCK_TTL_SECONDS)

    stmt = (
        select(OutboxEvent)
        .where(
            (
                (OutboxEvent.status == OutboxStatus.NEW.value)
                |
                (
                    (OutboxEvent.status == OutboxStatus.PROCESSING.value)
                    &
                    (OutboxEvent.locked_at < lock_expired)
                )
            ),
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.id.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )

    events = list(db.execute(stmt).scalars().all())

    for e in events:
        e.status = OutboxStatus.PROCESSING.value
        e.locked_at = now

    return events


# ------------------------------------------------------------
# SUCCESS
# ------------------------------------------------------------

def mark_published(db: Session, event_id: int) -> None:
    db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(
            status=OutboxStatus.PUBLISHED.value,
            published_at=_utc_now(),
            locked_at=None,
            last_error=None,
        )
    )


# ------------------------------------------------------------
# FAILURE / RETRY
# ------------------------------------------------------------

def mark_failed_retry(db: Session, event_id: int, err: str, attempts: int) -> None:

    if attempts >= MAX_ATTEMPTS:
        db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.FAILED.value,
                attempts=attempts,
                last_error=err[:2000],
                locked_at=None,
            )
        )
        return

    delay = min(300, 2 ** min(attempts, 8))

    db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(
            status=OutboxStatus.NEW.value,
            attempts=attempts,
            last_error=err[:2000],
            available_at=_utc_now() + timedelta(seconds=delay),
            locked_at=None,
        )
    )