# src/outbox_publisher.py
import os
import time
import json

import pika
from sqlalchemy.orm import Session

from db.database import SessionLocal
from service.broker import _declare_topology  # ок оставить так
from sqlalchemy import text
from src.config import (
    RABBIT_URL,
    RABBIT_QUEUE,
    RABBIT_EVENTS_EXCHANGE,
    RABBIT_EVENTS_QUEUE,
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

def wait_for_outbox_table(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while True:
        db = SessionLocal()
        try:
            db.execute(text("select 1 from outbox_events limit 1"))
            return
        except Exception as e:
            if time.time() > deadline:
                raise RuntimeError(f"outbox_events not ready after {timeout_seconds}s: {e!r}")
            print("[outbox] waiting for migrations (outbox_events not ready yet)...")
            time.sleep(2)
        finally:
            db.close()


def _declare_events_topology(ch: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """
    Топология для доменных событий (completed/failed):
    - topic exchange: RABBIT_EVENTS_EXCHANGE
    - queue: RABBIT_EVENTS_QUEUE
    - bind: routing_key = RABBIT_EVENTS_ROUTING_KEY
    """
    ch.exchange_declare(exchange=RABBIT_EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    ch.queue_declare(queue=RABBIT_EVENTS_QUEUE, durable=True)
    ch.queue_bind(queue=RABBIT_EVENTS_QUEUE, exchange=RABBIT_EVENTS_EXCHANGE, routing_key=RABBIT_EVENTS_ROUTING_KEY)


def publish_one(ch, event_type: str, payload: dict) -> None:
    """
    Публикация одного события в Rabbit с publisher confirms.
    Успех = отсутствие исключения.
    """

    # 1) Команда воркеру (как раньше): в очередь video.process
    if event_type == EVENT_VIDEO_PROCESS_REQUESTED:
        ch.basic_publish(
            exchange="",
            routing_key=RABBIT_QUEUE,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers={"x-retry-count": 0},
            ),
            mandatory=True,
        )
        return

    # 2) Доменные события: в events exchange (completed/failed)
    if event_type in (EVENT_VIDEO_PROCESS_COMPLETED, EVENT_VIDEO_PROCESS_FAILED):
        envelope = {"event_type": event_type, "payload": payload}
        ch.basic_publish(
            exchange=RABBIT_EVENTS_EXCHANGE,
            routing_key=RABBIT_EVENTS_ROUTING_KEY,
            body=json.dumps(envelope).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
            mandatory=True,
        )
        return

    raise RuntimeError(f"Unknown outbox event_type: {event_type}")


def main():
    params = pika.URLParameters(RABBIT_URL)
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
            conn = pika.BlockingConnection(params)
            ch = conn.channel()

            # Очереди/ретраи для worker-очереди
            _declare_topology(ch)

            # Exchange/queue для событий
            _declare_events_topology(ch)

            # publisher confirms
            ch.confirm_delivery()
            wait_for_outbox_table(timeout_seconds=90)

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
                                mark_failed_retry(db, e.id, str(ex), attempts=e.attempts + 1)

                finally:
                    db.close()

                if conn and conn.is_open:
                    conn.sleep(POLL_INTERVAL)
                else:
                    raise RuntimeError("Rabbit connection closed")

        except Exception as e:
            print(f"[outbox] crashed: {e!r}")
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
