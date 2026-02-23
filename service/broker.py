# service/broker.py
import json
import logging
import logging.config
import os
import time
from typing import Callable, Any, Dict, Optional

import pika

from src.config import (
    RABBIT_URL,
    RABBIT_QUEUE,
    RABBIT_EVENTS_EXCHANGE,
    RABBIT_EVENTS_QUEUE,
    RABBIT_EVENTS_ROUTING_KEY,
)

from service.correlation import (
    get_request_id,
    get_trace_id,
    set_correlation,
)

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая pika) ---
_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)
# ----------------------------------------------------------------------------------------

# logging
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("broker")

# ---- retry/dlq settings ----
MAX_RETRIES = int(os.getenv("VIDEO_MAX_RETRIES", "5"))
RETRY_DELAY_MS = int(os.getenv("VIDEO_RETRY_DELAY_MS", "30000"))  # 30s

QUEUE_MAIN = RABBIT_QUEUE
QUEUE_RETRY = f"{RABBIT_QUEUE}.retry"
QUEUE_DLQ = f"{RABBIT_QUEUE}.dlq"

EXCHANGE_RETRY = f"{RABBIT_QUEUE}.retry.x"
EXCHANGE_DLX = f"{RABBIT_QUEUE}.dlx.x"


def _connect() -> pika.BlockingConnection:
    params = pika.URLParameters(RABBIT_URL)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))
    return pika.BlockingConnection(params)


def ping() -> None:
    """Lightweight RabbitMQ connectivity check (for self_check())."""
    conn = _connect()
    try:
        ch = conn.channel()
        ch.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _declare_topology(ch: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """
    Topology:
    - MAIN queue: reject/nack(requeue=False) -> EXCHANGE_DLX -> DLQ
    - RETRY queue: TTL -> EXCHANGE_RETRY -> MAIN
    """
    ch.exchange_declare(exchange=EXCHANGE_DLX, exchange_type="direct", durable=True)
    ch.exchange_declare(exchange=EXCHANGE_RETRY, exchange_type="direct", durable=True)

    ch.queue_declare(queue=QUEUE_DLQ, durable=True)
    ch.queue_bind(queue=QUEUE_DLQ, exchange=EXCHANGE_DLX, routing_key=QUEUE_DLQ)

    ch.queue_declare(
        queue=QUEUE_MAIN,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_DLX,
            "x-dead-letter-routing-key": QUEUE_DLQ,
        },
    )

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

    ch.basic_qos(prefetch_count=1)


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


def _with_retry_count(headers: Dict[str, Any], retry_count: int) -> Dict[str, Any]:
    new_headers = dict(headers or {})
    new_headers["x-retry-count"] = retry_count
    return new_headers


def _get_retry_count(properties) -> int:
    headers = getattr(properties, "headers", None) or {}
    try:
        return int(headers.get("x-retry-count", 0) or 0)
    except Exception:
        return 0


def _extract_trace_headers(properties) -> Dict[str, Any]:
    headers = dict(getattr(properties, "headers", None) or {})

    rid = headers.get("x-request-id") or headers.get("X-Request-ID")
    tid = headers.get("x-trace-id") or headers.get("X-Trace-Id") or headers.get("X-Trace-ID")

    if rid and "x-request-id" not in headers:
        headers["x-request-id"] = rid
    if tid and "x-trace-id" not in headers:
        headers["x-trace-id"] = tid

    return headers


def publish_video_process(
    video_id: int,
    path: str,
    *,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    conn = _connect()
    try:
        ch = conn.channel()
        _declare_topology(ch)

        payload = {"video_id": int(video_id), "path": path}

        headers = {"x-retry-count": 0}
        if correlation_id:
            headers["x-request-id"] = correlation_id
        if trace_id:
            headers["x-trace-id"] = trace_id

        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_MAIN,
            body=json.dumps(payload).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=headers,
                correlation_id=correlation_id,
            ),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def publish_domain_event(
    event_type: str,
    payload: dict,
    *,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    conn = _connect()
    try:
        ch = conn.channel()
        _declare_events_topology(ch)

        envelope = {"event_type": event_type, "payload": payload}

        headers: Dict[str, Any] = {}
        if correlation_id:
            headers["x-request-id"] = correlation_id
        if trace_id:
            headers["x-trace-id"] = trace_id

        ch.basic_publish(
            exchange=RABBIT_EVENTS_EXCHANGE,
            routing_key=RABBIT_EVENTS_ROUTING_KEY,
            body=json.dumps(envelope).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                headers=headers or None,
                correlation_id=correlation_id,
            ),
            mandatory=True,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def consume_forever(handler: Callable[[Dict[str, Any]], None]) -> None:
    """
    A3: прокидываем rid/tid (headers) внутрь handler через payload["__headers__"].
    """
    params = pika.URLParameters(RABBIT_URL)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))

    while True:
        conn = None
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            _declare_topology(ch)

            def publish_to_retry(body: bytes, properties, retry_count: int) -> None:
                headers = _extract_trace_headers(properties)
                headers = _with_retry_count(headers, retry_count)

                ch.basic_publish(
                    exchange="",
                    routing_key=QUEUE_RETRY,
                    body=body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type=getattr(properties, "content_type", None) or "application/json",
                        headers=headers,
                        correlation_id=getattr(properties, "correlation_id", None),
                        message_id=getattr(properties, "message_id", None),
                    ),
                )

            def on_message(channel, method, properties, body: bytes):
                headers = _extract_trace_headers(properties)

                set_correlation(
                    request_id=headers.get("x-request-id") or getattr(properties, "correlation_id", None),
                    trace_id=headers.get("x-trace-id"),
                )

                try:
                    payload = json.loads(body.decode("utf-8"))
                    if isinstance(payload, dict):
                        payload["__headers__"] = headers

                    handler(payload)

                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return

                except Exception as e:
                    retry_count = _get_retry_count(properties) + 1

                    if retry_count <= MAX_RETRIES:
                        publish_to_retry(body, properties, retry_count)
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                        logger.warning("retry %s/%s in %sms: %r", retry_count, MAX_RETRIES, RETRY_DELAY_MS, e)
                        return

                    channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
                    logger.error("send to DLQ after %s retries: %r", MAX_RETRIES, e)
                    return

            ch.basic_consume(queue=QUEUE_MAIN, on_message_callback=on_message)
            logger.info("consumer started queue=%s retry=%s dlq=%s", QUEUE_MAIN, QUEUE_RETRY, QUEUE_DLQ)
            ch.start_consuming()

        except Exception as e:
            logger.exception("consumer crashed: %r", e)
            time.sleep(2)

        finally:
            try:
                if conn and conn.is_open:
                    conn.close()
            except Exception:
                pass