# src/outbox_publisher.py
import os
import time
import json

import pika
from sqlalchemy.orm import Session
from sqlalchemy import text

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


def wait_for_outbox_table(
    timeout_seconds: int = 60,
    sleep_seconds: float = 1.0,
    log_every_seconds: float = 2.0,
) -> None:
    """
    Ждём, пока миграции создадут public.outbox_events.

    Почему так:
    - to_regclass('public.outbox_events') — устойчивый чек существования таблицы в Postgres
    - не маскируем вечным "waiting..." любые другие ошибки (дадим понятный timeout)
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
            # Если таблицы нет — вернёт NULL
            exists = db.execute(
                text("select to_regclass('public.outbox_events')")
            ).scalar()

            if exists:
                return

            now = time.time()
            if now - last_log >= log_every_seconds:
                print("[outbox] waiting for migrations (outbox_events not ready yet)...")
                last_log = now

            time.sleep(sleep_seconds)

        except Exception as e:
            # Любая ошибка: запоминаем и ждём дальше до timeout
            last_err = e
            now = time.time()
            if now - last_log >= log_every_seconds:
                print(f"[outbox] waiting for migrations (db not ready): {e!r}")
                last_log = now
            time.sleep(sleep_seconds)

        finally:
            db.close()


def publish_one(ch, event_type: str, payload) -> None:
    """
    payload ожидается как ENVELOPE dict (event_id, event_type, schema_version, correlation_id, trace_id, payload, ...)
    """
    rid = payload.get("correlation_id") if isinstance(payload, dict) else None
    body = json.dumps(payload).encode("utf-8")

    # 1) Команда воркеру: в очередь video.process
    if event_type == EVENT_VIDEO_PROCESS_REQUESTED:
        ch.basic_publish(
            exchange="",
            routing_key=RABBIT_QUEUE,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers={"x-retry-count": 0},
                correlation_id=rid,
            ),
            mandatory=True,
        )
        return

    # 2) Доменные события: в events exchange (completed/failed)
    if event_type in (EVENT_VIDEO_PROCESS_COMPLETED, EVENT_VIDEO_PROCESS_FAILED):
        ch.basic_publish(
            exchange=RABBIT_EVENTS_EXCHANGE,
            routing_key=RABBIT_EVENTS_ROUTING_KEY,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=rid,
            ),
            mandatory=True,
        )
        return

    raise RuntimeError(f"Unknown outbox event_type: {event_type}")


def main() -> None:
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
            # 1) Ждём БД/таблицу ДО старта работы (Rabbit может быть уже поднят, но БД/миграции — нет)
            wait_for_outbox_table(timeout_seconds=90, sleep_seconds=1.0)

            # 2) Подключаемся к Rabbit
            conn = pika.BlockingConnection(params)
            ch = conn.channel()

            # Очереди/ретраи для worker-очереди
            _declare_topology(ch)
            # Exchange/queue для событий
            _declare_events_topology(ch)
            # publisher confirms
            ch.confirm_delivery()

            print("[outbox] boot: started publisher loop")

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
                                # фиксируем ошибку + увеличиваем attempts
                                mark_failed_retry(db, e.id, str(ex), attempts=(e.attempts or 0) + 1)

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