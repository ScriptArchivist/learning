# src/outbox_publisher.py
import os
import time
import json

import pika
from sqlalchemy.orm import Session

from db.database import SessionLocal
from service.broker import _declare_topology  # можно оставить так, либо вынести публично
from src.config import RABBIT_URL, RABBIT_QUEUE
from service.outbox import (
    fetch_pending_batch,
    mark_published,
    mark_failed_retry,
    EVENT_VIDEO_PROCESS_REQUESTED,
)

BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))
POLL_INTERVAL = float(os.getenv("OUTBOX_POLL_INTERVAL", "0.5"))


def publish_one(ch, event_type: str, payload: dict) -> None:
    """
    Публикация одного события в Rabbit.

    В pika BlockingConnection basic_publish() обычно возвращает None.
    В режиме confirm_delivery() ошибки доставки приходят исключениями:
    - pika.exceptions.UnroutableError (mandatory=True и нет маршрута)
    - pika.exceptions.NackError (broker nack)
    - pika.exceptions.ChannelClosedByBroker и т.п.
    """
    if event_type != EVENT_VIDEO_PROCESS_REQUESTED:
        raise RuntimeError(f"Unknown outbox event_type: {event_type}")

    ch.basic_publish(
        exchange="",
        routing_key=RABBIT_QUEUE,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
            headers={"x-retry-count": 0},
        ),
        mandatory=True,  # если не доставилось никуда — получим исключение
    )


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

            _declare_topology(ch)

            # publisher confirms (в BlockingConnection это режим, а не "wait_for_confirms")
            ch.confirm_delivery()

            while True:
                db: Session = SessionLocal()
                try:
                    with db.begin():
                        events = fetch_pending_batch(db, limit=BATCH_SIZE)

                        if events:
                            for e in events:
                                try:
                                    # publish_one может вернуть None в pika (это нормально),
                                    # поэтому считаем успехом отсутствие исключения
                                    publish_one(ch, e.event_type, e.payload)
                                    mark_published(db, e.id)

                                except Exception as ex:
                                    mark_failed_retry(
                                        db,
                                        e.id,
                                        str(ex),
                                        attempts=e.attempts + 1,
                                    )

                finally:
                    db.close()

                # ВАЖНО: вместо time.sleep — conn.sleep (обслуживает heartbeats и I/O)
                if conn and conn.is_open:
                    conn.sleep(POLL_INTERVAL)
                else:
                    # если соединение уже умерло — вывалимся наружу, переподключимся
                    raise RuntimeError("Rabbit connection closed")

        except Exception as e:
            # repr, чтобы не было "пусто"
            print(f"[outbox] crashed: {e!r}")
            # тут conn уже может быть None/closed, поэтому обычный sleep
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
