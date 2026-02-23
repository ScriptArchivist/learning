# service/outbox.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from db.models import OutboxEvent, OutboxStatus
from service.events import EventEnvelope
from service.events import EventEnvelope, SCHEMA_VERSION
from service.correlation import ensure_request_id, ensure_trace_id


EVENT_VIDEO_PROCESS_COMPLETED = "video.process.completed"
EVENT_VIDEO_PROCESS_FAILED = "video.process.failed"
EVENT_VIDEO_PROCESS_REQUESTED = "video.process.requested"

# schema versions (меняешь payload -> bump version)
SCHEMA_VERSIONS: dict[str, int] = {
    EVENT_VIDEO_PROCESS_REQUESTED: 1,
    EVENT_VIDEO_PROCESS_COMPLETED: 1,
    EVENT_VIDEO_PROCESS_FAILED: 1,
}


def _utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def build_envelope(
    *,
    event_type: str,
    payload: dict[str, Any],
    producer: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    schema_version: int | None = None,
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": schema_version or SCHEMA_VERSIONS.get(event_type, 1),
        "occurred_at": occurred_at or _utc_iso(),
        "producer": producer,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "payload": payload,
    }


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
    """
    Создаёт outbox-событие.
    В payload БД всегда хранится полноценный EventEnvelope.
    """

    # Гарантируем rid/tid на уровне outbox, даже если вызывающий код забыл прокинуть
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
        event_type=event_type,  # отдельная колонка для индексов
        payload=envelope.model_dump(mode="json"),  # всегда валидированный envelope
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        available_at=available_at or datetime.utcnow(),
        status=OutboxStatus.PENDING.value,
        attempts=0,
    )

    db.add(evt)
    return evt


def fetch_pending_batch(db: Session, *, limit: int) -> list[OutboxEvent]:
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
