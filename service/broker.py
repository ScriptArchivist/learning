# service/broker.py
import json
import logging
import logging.config
import os
import time
from typing import Any, Callable, Dict, Optional

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

# --- logging: гарантируем rid/tid в любых логах ---
_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("broker")

# ---- retry settings ----
MAX_RETRIES = int(os.getenv("VIDEO_MAX_RETRIES", "5"))          # количество RETRY (не считая первую попытку)
RETRY_DELAY_MS = int(os.getenv("VIDEO_RETRY_DELAY_MS", "30000"))  # база экспоненциальной задержки

QUEUE_MAIN = RABBIT_QUEUE                      # обычно "video.process"
QUEUE_RETRY = f"{RABBIT_QUEUE}.retry"          # "video.process.retry"
QUEUE_DLQ = f"{RABBIT_QUEUE}.dlq"              # "video.process.dlq"

EXCHANGE_RETRY = f"{RABBIT_QUEUE}.retry.x"     # direct
EXCHANGE_DLX = f"{RABBIT_QUEUE}.dlx.x"         # direct


def _connect() -> pika.BlockingConnection:
    params = pika.URLParameters(RABBIT_URL)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.blocked_connection_timeout = int(os.getenv("RABBIT_BLOCKED_TIMEOUT", "120"))
    return pika.BlockingConnection(params)


def _declare_topology(ch) -> None:
    """
    Схема:
      MAIN --(reject requeue=False)--> EXCHANGE_RETRY -> QUEUE_RETRY
      QUEUE_RETRY (per-message TTL via 'expiration') --(DLX to default exchange)--> MAIN
      DLQ отдельная очередь, кладём туда явно.
    """
    ch.exchange_declare(exchange=EXCHANGE_DLX, exchange_type="direct", durable=True)
    ch.exchange_declare(exchange=EXCHANGE_RETRY, exchange_type="direct", durable=True)

    # DLQ
    ch.queue_declare(queue=QUEUE_DLQ, durable=True)
    ch.queue_bind(queue=QUEUE_DLQ, exchange=EXCHANGE_DLX, routing_key=QUEUE_DLQ)

    # MAIN: если reject(requeue=False), Rabbit отправит в EXCHANGE_RETRY/QUEUE_RETRY
    ch.queue_declare(
        queue=QUEUE_MAIN,
        durable=True,
        arguments={
            "x-dead-letter-exchange": EXCHANGE_RETRY,
            "x-dead-letter-routing-key": QUEUE_RETRY,
        },
    )

    # RETRY: TTL per-message задаём через BasicProperties.expiration
    # после истечения TTL сообщение вернётся в MAIN через default exchange
    ch.queue_declare(
        queue=QUEUE_RETRY,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": QUEUE_MAIN,
        },
    )

    ch.basic_qos(prefetch_count=1)


def _declare_events_topology(ch) -> None:
    ch.exchange_declare(exchange=RABBIT_EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    ch.queue_declare(queue=RABBIT_EVENTS_QUEUE, durable=True)
    ch.queue_bind(
        queue=RABBIT_EVENTS_QUEUE,
        exchange=RABBIT_EVENTS_EXCHANGE,
        routing_key=RABBIT_EVENTS_ROUTING_KEY,
    )


def publish_worker_envelope(
    envelope: dict,
    *,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    """
    Публикуем в worker MAIN queue напрямую (default exchange).
    Это именно то, что должен читать src/worker.py (EventEnvelope).
    """
    conn = _connect()
    try:
        ch = conn.channel()
        _declare_topology(ch)

        headers: Dict[str, Any] = {}
        if correlation_id:
            headers["x-request-id"] = correlation_id
        if trace_id:
            headers["x-trace-id"] = trace_id

        ch.basic_publish(
            exchange="",
            routing_key=QUEUE_MAIN,
            body=json.dumps(envelope).encode(),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=correlation_id,
                headers=headers or None,
            ),
        )
    finally:
        conn.close()


def publish_domain_event(
    event_type: str,
    payload: dict,
    *,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    """
    1) video.process.requested — отправляем напрямую в worker queue (MAIN) как envelope.
       (иначе можно легко получить "published в outbox, но worker не видит")
    2) все остальные доменные события — в topic exchange как раньше
    """
    # импорт локально, чтобы не сделать круговой импорт
    from service.outbox import EVENT_VIDEO_PROCESS_REQUESTED

    if event_type == EVENT_VIDEO_PROCESS_REQUESTED:
        envelope = {
            "schema_version": "1.0",
            "event_id": str(os.getenv("HOSTNAME", "worker-producer")) + ":" + str(time.time_ns()),
            "event_type": event_type,
            "payload": payload,
            "occurred_at": time.time(),
            "correlation_id": correlation_id,
            "trace_id": trace_id,
        }
        publish_worker_envelope(envelope, correlation_id=correlation_id, trace_id=trace_id)
        return

    conn = _connect()
    try:
        ch = conn.channel()
        _declare_events_topology(ch)

        envelope = {"event_type": event_type, "payload": payload}

        ch.basic_publish(
            exchange=RABBIT_EVENTS_EXCHANGE,
            routing_key=RABBIT_EVENTS_ROUTING_KEY,
            body=json.dumps(envelope).encode(),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
                correlation_id=correlation_id,
            ),
            mandatory=True,
        )
    finally:
        conn.close()


def _get_retry_count_from_headers(headers: Dict[str, Any]) -> int:
    """
    Считаем x-death по QUEUE_RETRY.
    """
    deaths = headers.get("x-death") or []
    for d in deaths:
        if d.get("queue") == QUEUE_RETRY:
            try:
                return int(d.get("count", 0))
            except Exception:
                return 0
    return 0


def consume_forever(handler: Callable[[Dict[str, Any], int], None]) -> None:
    """
    Consumer на MAIN:
      - на успех -> ack
      - на исключение -> reject(requeue=False) => уходит в RETRY (через DLX из MAIN)
      - по достижении MAX_RETRIES handler может сам решить "последняя попытка" и
        сгенерировать fail-событие/запись, а мы всё равно отправим сообщение в retry/dlq?
        Здесь мы делаем так:
          * если handler выбросил -> мы reject(requeue=False) (Rabbit сам перегонит в RETRY)
        А DLQ мы используем в handler (явной публикацией), чтобы не зависеть от policy.
    """
    params = pika.URLParameters(RABBIT_URL)

    while True:
        conn = None
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            _declare_topology(ch)

            def on_message(channel, method, properties, body):
                headers = (properties.headers or {}) if properties else {}
                retry_count = _get_retry_count_from_headers(headers)

                # correlation для логов / контекста
                set_correlation(
                    request_id=headers.get("x-request-id") or getattr(properties, "correlation_id", None),
                    trace_id=headers.get("x-trace-id"),
                )

                try:
                    payload = json.loads(body.decode())

                    # прокинем headers, если handler захочет
                    if isinstance(payload, dict):
                        payload["__headers__"] = headers

                    handler(payload, retry_count)
                    channel.basic_ack(delivery_tag=method.delivery_tag)

                except Exception:
                    logger.exception("handler failed, reject to retry (retry_count=%s)", retry_count)
                    # отправит в EXCHANGE_RETRY -> QUEUE_RETRY (из аргументов MAIN)
                    channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)

            ch.basic_consume(queue=QUEUE_MAIN, on_message_callback=on_message)
            logger.info("consumer started queue=%s retry=%s dlq=%s", QUEUE_MAIN, QUEUE_RETRY, QUEUE_DLQ)
            ch.start_consuming()

        except Exception as e:
            logger.exception("consumer crashed: %r", e)
            time.sleep(2)

        finally:
            if conn and conn.is_open:
                conn.close()