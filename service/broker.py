# service/broker.py
import json
import os
import time
from typing import Callable, Any, Dict

import pika

from src.config import RABBIT_URL, RABBIT_QUEUE

# ---- retry/dlq settings ----
MAX_RETRIES = int(os.getenv("VIDEO_MAX_RETRIES", "5"))
RETRY_DELAY_MS = int(os.getenv("VIDEO_RETRY_DELAY_MS", "30000"))  # 30s

QUEUE_MAIN = RABBIT_QUEUE
QUEUE_RETRY = f"{RABBIT_QUEUE}.retry"
QUEUE_DLQ = f"{RABBIT_QUEUE}.dlq"

# Явные exchange'и (самый надежный вариант)
EXCHANGE_RETRY = f"{RABBIT_QUEUE}.retry.x"
EXCHANGE_DLX = f"{RABBIT_QUEUE}.dlx.x"


def _connect() -> pika.BlockingConnection:
    params = pika.URLParameters(RABBIT_URL)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))
    return pika.BlockingConnection(params)


def _declare_topology(ch: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """
    Topology:
    - MAIN queue: reject/nack(requeue=False) -> EXCHANGE_DLX -> DLQ
    - RETRY queue: TTL -> EXCHANGE_RETRY -> MAIN
    """

    # exchanges
    ch.exchange_declare(exchange=EXCHANGE_DLX, exchange_type="direct", durable=True)
    ch.exchange_declare(exchange=EXCHANGE_RETRY, exchange_type="direct", durable=True)

    # DLQ queue + bind
    ch.queue_declare(queue=QUEUE_DLQ, durable=True)
    ch.queue_bind(queue=QUEUE_DLQ, exchange=EXCHANGE_DLX, routing_key=QUEUE_DLQ)

    # MAIN queue: dead-letter -> DLQ
    ch.queue_declare(
        queue=QUEUE_MAIN,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": QUEUE_DLQ,
        },
    )

    # RETRY queue: TTL -> dead-letter -> MAIN
    ch.queue_declare(
        queue=QUEUE_RETRY,
        durable=True,
        arguments={
            "x-message-ttl": RETRY_DELAY_MS,
            "x-dead-letter-exchange": EXCHANGE_RETRY,
            "x-dead-letter-routing-key": QUEUE_MAIN,
        },
    )
    ch.queue_bind(queue=QUEUE_MAIN, exchange=EXCHANGE_RETRY, routing_key=QUEUE_MAIN)

    # один воркер = одно сообщение
    ch.basic_qos(prefetch_count=1)


def publish_video_process(video_id: int, path: str) -> None:
    """Публикует задачу обработки видео в Rabbit (durable message)."""
    conn = _connect()
    try:
        ch = conn.channel()
        _declare_topology(ch)

        payload = {"video_id": int(video_id), "path": path}

        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_MAIN,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent
                content_type="application/json",
                headers={"x-retry-count": 0},
            ),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def consume_forever(handler: Callable[[Dict[str, Any]], None]) -> None:
    """
    Consumer:
    - manual ack/reject
    - retry через QUEUE_RETRY (TTL) и возврат в QUEUE_MAIN через EXCHANGE_RETRY
    - лимит попыток -> reject(requeue=False) -> DLQ (через EXCHANGE_DLX)
    """
    params = pika.URLParameters(RABBIT_URL)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))

    def get_retry_count(properties) -> int:
        headers = getattr(properties, "headers", None) or {}
        try:
            return int(headers.get("x-retry-count", 0) or 0)
        except Exception:
            return 0

    while True:
        conn = None
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            _declare_topology(ch)

            def publish_to_retry(body: bytes, properties, retry_count: int) -> None:
                headers = dict(getattr(properties, "headers", None) or {})
                headers["x-retry-count"] = retry_count

                ch.basic_publish(
                    exchange="",
                    routing_key=QUEUE_RETRY,
                    body=body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type=getattr(properties, "content_type", None) or "application/json",
                        headers=headers,
                    ),
                )

            def on_message(channel, method, properties, body: bytes):
                try:
                    payload = json.loads(body.decode("utf-8"))
                    handler(payload)

                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return

                except Exception as e:
                    retry_count = get_retry_count(properties) + 1

                    if retry_count <= MAX_RETRIES:
                        publish_to_retry(body, properties, retry_count)
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                        print(f"[broker] retry {retry_count}/{MAX_RETRIES} in {RETRY_DELAY_MS}ms: {e}")
                        return

                    channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                    print(f"[broker] send to DLQ after {MAX_RETRIES} retries: {e}")
                    return

            ch.basic_consume(queue=QUEUE_MAIN, on_message_callback=on_message)
            ch.start_consuming()

        except Exception as e:
            print(f"[broker] consumer crashed: {e}")
            time.sleep(2)

        finally:
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass
