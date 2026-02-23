# src/outbox_publisher.py
import os
import time
import json
import logging
import logging.config

import pika
from sqlalchemy.orm import Session
from sqlalchemy import text

from service.correlation import (
    get_request_id,
    get_trace_id,
    set_correlation,
)

from db.database import SessionLocal
from service.broker import _declare_topology, _declare_events_topology
from src.config import (
    RABBIT_URL,
    RABBIT_QUEUE,
    RABBIT_EVENTS_EXCHANGE,
    RABBIT_EVENTS_ROUTING_KEY,
)
from service.outbox import (
    fetch_pending_batch,
    mark_published,
    mark_failed_retry,
    EVENT_VIDEO_PROCESS_REQUESTED,
    EVENT_VIDEO_PROCESS_COMPLETED,
    EVENT_VIDEO_PROCESS_FAILED,
)

BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))
POLL_INTERVAL = float(os.getenv("OUTBOX_POLL_INTERVAL", "0.5"))

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая pika) ---
_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)
# ----------------------------------------------------------------------------------------

# logging.ini (после factory!)
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("outbox")


def wait_for_outbox_table(
    timeout_seconds: int = 60,
    sleep_seconds: float = 1.0,
    log_every_seconds: float = 2.0,
) -> None:
    """
    Ждём, пока миграции создадут public.outbox_events.
    """
    deadline = time.time() + timeout_seconds
    last_log = 0.0
    last_err: Exception | None = None

    while True:
        if time.time() > deadline:
            raise RuntimeError(
                f"outbox_events not ready after {timeout_seconds}s"
                + (f": last_err={last_err!r}" if last_err else "")
            )

        db: Session = SessionLocal()
        try:
            exists = db.execute(text("select to_regclass('public.outbox_events')")).scalar()
            if exists:
                return

            now = time.time()
            if now - last_log >= log_every_seconds:
                logger.warning("waiting for migrations (outbox_events not ready yet)...")
                last_log = now

            time.sleep(sleep_seconds)

        except Exception as e:
            last_err = e
            now = time.time()
            if now - last_log >= log_every_seconds:
                logger.warning("waiting for migrations (db not ready): %r", e)
                last_log = now
            time.sleep(sleep_seconds)

        finally:
            db.close()


def publish_one(ch, event_type: str, payload) -> None:
    """
    payload ожидается как ENVELOPE dict (event_id, event_type, schema_version, correlation_id, trace_id, payload, ...)
    """
    if not isinstance(payload, dict):
        raise RuntimeError(f"outbox payload must be dict envelope, got: {type(payload)}")

    rid = payload.get("correlation_id")
    tid = payload.get("trace_id")

    # Контекст корреляции для логов publisher'а
    set_correlation(request_id=rid, trace_id=tid)

    body = json.dumps(payload).encode("utf-8")

    headers = {
        "x-retry-count": 0,
        "x-request-id": rid,
        "x-trace-id": tid,
    }

    # 1) Команда воркеру
    if event_type == EVENT_VIDEO_PROCESS_REQUESTED:
        ch.basic_publish(
            exchange="",
            routing_key=RABBIT_QUEUE,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=headers,
                correlation_id=rid,
                message_id=str(payload.get("event_id") or ""),
            ),
            mandatory=True,
        )
        logger.info("published to worker queue event_type=%s event_id=%s", event_type, payload.get("event_id"))
        return

    # 2) Доменные события
    if event_type in (EVENT_VIDEO_PROCESS_COMPLETED, EVENT_VIDEO_PROCESS_FAILED):
        ch.basic_publish(
            exchange=RABBIT_EVENTS_EXCHANGE,
            routing_key=RABBIT_EVENTS_ROUTING_KEY,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=headers,
                correlation_id=rid,
                message_id=str(payload.get("event_id") or ""),
            ),
            mandatory=True,
        )
        logger.info("published to events exchange event_type=%s event_id=%s", event_type, payload.get("event_id"))
        return

    raise RuntimeError(f"Unknown outbox event_type: {event_type}")


def self_check(params: pika.URLParameters) -> None:
    # 1) DB ping
    db: Session = SessionLocal()
    try:
        db.execute(text("select 1"))
    finally:
        db.close()

    # 2) Rabbit connect ping
    conn = pika.BlockingConnection(params)
    try:
        ch = conn.channel()
        ch.close()
    finally:
        conn.close()

    logger.info("self_check: ok (db + rabbit)")


def main() -> None:
    params = pika.URLParameters(RABBIT_URL)

    # Быстрый self-check перед стартом
    try:
        self_check(params)
    except Exception as e:
        logger.exception("self_check failed: %r", e)

    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))

    # чтобы логи сразу появлялись в docker logs
    try:
        import sys
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    while True:
        conn = None
        ch = None
        try:
            wait_for_outbox_table(timeout_seconds=90, sleep_seconds=1.0)

            conn = pika.BlockingConnection(params)
            ch = conn.channel()

            _declare_topology(ch)
            _declare_events_topology(ch)

            ch.confirm_delivery()

            logger.info("boot: started publisher loop")

            while True:
                db: Session = SessionLocal()
                try:
                    with db.begin():
                        events = fetch_pending_batch(db, limit=BATCH_SIZE)

                        for e in events:
                            try:
                                publish_one(ch, e.event_type, e.payload)
                                mark_published(db, e.id)
                            except Exception as ex:
                                mark_failed_retry(db, e.id, str(ex), attempts=(e.attempts or 0) + 1)
                finally:
                    db.close()

                if conn and conn.is_open:
                    conn.sleep(POLL_INTERVAL)
                else:
                    raise RuntimeError("Rabbit connection closed")

        except Exception as e:
            logger.exception("crashed: %r", e)
            time.sleep(2)

        finally:
            try:
                if ch and ch.is_open:
                    ch.close()
            except Exception:
                pass
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()