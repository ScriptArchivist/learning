# src/outbox_publisher.py
from __future__ import annotations

import logging
import logging.config
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocalWrite
from service.outbox import fetch_pending_batch, mark_failed_retry, mark_published

from db.models import OutboxEvent, OutboxStatus
from src.metrics import (
    get_service_name,
    inc_outbox_publish_attempt,
    inc_outbox_published,
    set_outbox_backlog,
    set_outbox_failed,
    start_background_metrics_server,
)

# publish_domain_event already knows:
# - video.process.requested -> MAIN queue (worker)
# - others -> topic exchange
from service.broker import publish_domain_event


logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("outbox-publisher")

# Pika can be very noisy on network failures (which are expected for outbox retry).
# Make it quiet to avoid megabytes of stacktraces in logs.
logging.getLogger("pika").setLevel(logging.CRITICAL)

SERVICE_NAME = get_service_name("outbox-publisher")


class OutboxItem(TypedDict):
    id: int
    event_type: str
    envelope: Dict[str, Any]  # stored EventEnvelope (dict)
    attempts: int


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if not v:
        return default
    try:
        return float(v)
    except Exception:
        return default


BATCH_SIZE = _env_int("OUTBOX_BATCH_SIZE", 50)
POLL_INTERVAL = _env_float("OUTBOX_POLL_INTERVAL", 0.5)

# Leader election between replicas
LEADER_LOCK_KEY = _env_int("OUTBOX_LEADER_LOCK_KEY", 424242)
LEADER_REFRESH_SECONDS = _env_float("OUTBOX_LEADER_REFRESH_SECONDS", 2.0)


@contextmanager
def _session() -> Session:
    db = SessionLocalWrite()
    try:
        yield db
    finally:
        db.close()


def _try_advisory_lock(db: Session, lock_key: int) -> bool:
    # pg_try_advisory_lock is held by the *connection*.
    got = db.execute(text("select pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar()
    return bool(got)


def _snapshot_events(events: list) -> List[OutboxItem]:
    """
    Convert ORM objects into plain dicts while still bound to Session.
    Prevents DetachedInstanceError later.
    """
    snapped: List[OutboxItem] = []
    for e in events:
        envelope = e.payload
        if envelope is None:
            envelope = {}
        if not isinstance(envelope, dict):
            envelope = {"_raw_payload": str(envelope)}

        snapped.append(
            {
                "id": int(e.id),
                "event_type": str(e.event_type),
                "envelope": envelope,
                "attempts": int(getattr(e, "attempts", 0) or 0),
            }
        )
    return snapped


def _extract_correlation(envelope: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    rid = envelope.get("correlation_id") if isinstance(envelope, dict) else None
    tid = envelope.get("trace_id") if isinstance(envelope, dict) else None
    return (rid, tid)


def _safe_err(e: Exception, limit: int = 800) -> str:
    s = f"{type(e).__name__}: {e}"
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s[:limit]


def _refresh_outbox_metrics() -> None:
    with _session() as db:
        backlog = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.status.in_([OutboxStatus.NEW.value, OutboxStatus.PROCESSING.value]))
            .count()
        )
        failed = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.status == OutboxStatus.FAILED.value)
            .count()
        )

    set_outbox_backlog(SERVICE_NAME, int(backlog))
    set_outbox_failed(SERVICE_NAME, int(failed))


def _publish_one(it: OutboxItem) -> None:
    event_id = it["id"]
    event_type = it["event_type"]
    envelope = it["envelope"]

    if not isinstance(envelope, dict):
        raise ValueError(f"outbox envelope is not a dict (event_id={event_id})")

    rid, tid = _extract_correlation(envelope)

    domain_payload = envelope.get("payload")
    if not isinstance(domain_payload, dict):
        raise ValueError(f"envelope.payload is not a dict (event_id={event_id})")

    publish_domain_event(
        event_type,
        domain_payload,
        correlation_id=rid,
        trace_id=tid,
    )


def main() -> None:
    logger.info(
        "boot: outbox-publisher batch=%s poll=%s lock_key=%s",
        BATCH_SIZE,
        POLL_INTERVAL,
        LEADER_LOCK_KEY,
    )
    start_background_metrics_server(int(os.getenv("METRICS_PORT", "9100")))
    _refresh_outbox_metrics()

    # Leader keeps this session open to hold pg advisory lock.
    leader_db: Optional[Session] = None

    while True:
        # 1) Ensure leader
        if leader_db is None:
            try:
                leader_db = SessionLocalWrite()
                if not _try_advisory_lock(leader_db, LEADER_LOCK_KEY):
                    leader_db.close()
                    leader_db = None
                    time.sleep(LEADER_REFRESH_SECONDS)
                    continue

                logger.info("leader lock acquired key=%s", LEADER_LOCK_KEY)
            except Exception as e:
                logger.warning("leader acquire failed err=%s", _safe_err(e), exc_info=False)
                if leader_db is not None:
                    try:
                        leader_db.close()
                    except Exception:
                        pass
                    leader_db = None
                time.sleep(LEADER_REFRESH_SECONDS)
                continue

        try:
            # 2) Claim batch and snapshot in a short transaction
            items: List[OutboxItem] = []
            with _session() as db:
                with db.begin():
                    events = fetch_pending_batch(db, limit=BATCH_SIZE)
                    if events:
                        items = _snapshot_events(events)

            if not items:
                _refresh_outbox_metrics()
                time.sleep(POLL_INTERVAL)
                continue

            _refresh_outbox_metrics()

            # 3) Publish each item and mark result
            for it in items:
                event_id = it["id"]
                event_type = it["event_type"]
                attempts_next = it["attempts"] + 1

                inc_outbox_publish_attempt(SERVICE_NAME, event_type)

                try:
                    _publish_one(it)

                    with _session() as db:
                        with db.begin():
                            mark_published(db, event_id)

                    inc_outbox_published(SERVICE_NAME, event_type)
                    logger.info("published event_id=%s type=%s", event_id, event_type)

                except Exception as e:
                    err = _safe_err(e)

                    with _session() as db:
                        with db.begin():
                            mark_failed_retry(db, event_id, err, attempts_next)

                    logger.warning(
                        "publish failed event_id=%s type=%s attempts=%s err=%s",
                        event_id,
                        event_type,
                        attempts_next,
                        err,
                        exc_info=False,
                    )

            _refresh_outbox_metrics()
            time.sleep(0.01)

        except Exception as e:
            logger.warning("loop error, reset leader err=%s", _safe_err(e), exc_info=False)

            if leader_db is not None:
                try:
                    leader_db.close()
                except Exception:
                    pass
                leader_db = None

            time.sleep(LEADER_REFRESH_SECONDS)


if __name__ == "__main__":
    main()