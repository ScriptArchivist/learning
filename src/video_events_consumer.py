# src/video_events_consumer.py
from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import datetime
from typing import Any, Optional, Tuple

import pika
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Video, VideoStatus
from service.correlation import get_request_id, get_trace_id, set_correlation
from service.video_status import transition_video_status, VideoStatusTransitionError

from src.config import (
    RABBIT_URL,
    RABBIT_EVENTS_EXCHANGE,
    RABBIT_EVENTS_QUEUE,
    RABBIT_EVENTS_ROUTING_KEY,
)

# --- LogRecordFactory: request_id/trace_id для formatter'а logging.ini ---
_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)

logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("video-events-consumer")


def _connect() -> pika.BlockingConnection:
    url = RABBIT_URL or ""
    params = pika.URLParameters(url)
    params.heartbeat = int(os.getenv("RABBIT_HEARTBEAT", "60"))
    params.socket_timeout = float(os.getenv("RABBIT_SOCKET_TIMEOUT_SECONDS", "5"))
    params.stack_timeout = float(os.getenv("RABBIT_STACK_TIMEOUT_SECONDS", "10"))
    return pika.BlockingConnection(params)


def _safe_json_loads(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _extract_event(message: Any) -> Tuple[Optional[str], Optional[dict]]:
    """
    Поддерживаем:
      1) {"event_type": "...", "payload": {...}}
      2) outbox envelope целиком (те же ключи + meta)
      3) иногда встречается {"data": {...}} — попробуем достать оттуда
    """
    if not isinstance(message, dict):
        return None, None

    # вариант "data": {...}
    if "event_type" not in message and isinstance(message.get("data"), dict):
        message = message["data"]

    et = message.get("event_type")
    pl = message.get("payload")

    if not isinstance(et, str) or not et:
        return None, None
    if not isinstance(pl, dict):
        return et, None
    return et, pl


def _get_video(db: Session, video_id: int) -> Optional[Video]:
    return db.query(Video).filter(Video.id == video_id).one_or_none()


def _try_transition(video: Video, target: VideoStatus, *, actor: str, **kwargs) -> bool:
    """
    True если статус реально изменился.
    """
    before = video.status
    try:
        transition_video_status(video, target, actor=actor, **kwargs)
        return before != video.status
    except VideoStatusTransitionError:
        return False


def _apply_upload_completed(db: Session, pl: dict) -> None:
    video_id = int(pl["video_id"])
    video = _get_video(db, video_id)
    if not video:
        logger.info("skip upload_completed: video not found video_id=%s", video_id)
        return

    # UPLOADING -> UPLOADED
    changed = _try_transition(video, VideoStatus.UPLOADED, actor="api")

    # доп. поля (необязательные)
    if pl.get("size_bytes") is not None:
        video.size_bytes = int(pl["size_bytes"])
    if pl.get("content_type"):
        video.mime_type = str(pl["content_type"])

    logger.info(
        "applied event=upload_completed video_id=%s status=%s changed=%s",
        video_id,
        video.status.value,
        changed,
    )


def _apply_processing_started(db: Session, pl: dict) -> None:
    video_id = int(pl["video_id"])
    video = _get_video(db, video_id)
    if not video:
        logger.info("skip processing_started: video not found video_id=%s", video_id)
        return

    # UPLOADED -> PROCESSING (или уже PROCESSING/READY — no-op)
    changed = _try_transition(video, VideoStatus.PROCESSING, actor="worker")
    logger.info(
        "applied event=processing_started video_id=%s status=%s changed=%s",
        video_id,
        video.status.value,
        changed,
    )


def _apply_processing_done(db: Session, pl: dict) -> None:
    video_id = int(pl["video_id"])
    video = _get_video(db, video_id)
    if not video:
        logger.info("skip processing_done: video not found video_id=%s", video_id)
        return

    before = video.status

    # catch-up (на случай если "started" потеряли):
    if video.status == VideoStatus.UPLOADED:
        _try_transition(video, VideoStatus.PROCESSING, actor="worker")

    changed_ready = _try_transition(video, VideoStatus.READY, actor="worker", processed_at=datetime.utcnow())

    logger.info(
        "applied event=processing_done video_id=%s status_before=%s status_after=%s changed_ready=%s",
        video_id,
        before.value if hasattr(before, "value") else str(before),
        video.status.value,
        changed_ready,
    )


def _apply_processing_failed(db: Session, pl: dict) -> None:
    video_id = int(pl["video_id"])
    video = _get_video(db, video_id)
    if not video:
        logger.info("skip processing_failed: video not found video_id=%s", video_id)
        return

    err = pl.get("error") or "processing failed"
    before = video.status

    if video.status == VideoStatus.UPLOADED:
        _try_transition(video, VideoStatus.PROCESSING, actor="worker")

    changed_failed = _try_transition(video, VideoStatus.FAILED, actor="worker", error_message=str(err))

    logger.info(
        "applied event=processing_failed video_id=%s status_before=%s status_after=%s changed_failed=%s err=%s",
        video_id,
        before.value if hasattr(before, "value") else str(before),
        video.status.value,
        changed_failed,
        str(err)[:200],
    )


def _handle_event(db: Session, message: Any) -> None:
    event_type, pl = _extract_event(message)
    if not event_type:
        return
    if not pl:
        logger.debug("skip: event_type=%s has no dict payload", event_type)
        return

    if event_type in ("UPLOAD_COMPLETED", "upload.completed", "video.upload.completed"):
        _apply_upload_completed(db, pl)
        return

    if event_type in ("PROCESSING_STARTED", "video.process.started"):
        _apply_processing_started(db, pl)
        return

    if event_type in ("PROCESSING_DONE", "video.process.done", "video.process.completed"):
        _apply_processing_done(db, pl)
        return

    if event_type in ("PROCESSING_FAILED", "video.process.failed"):
        _apply_processing_failed(db, pl)
        return

    logger.debug("skip: unknown event_type=%s payload_keys=%s", event_type, sorted(pl.keys()))


def main() -> None:
    # ВАЖНО:
    # - Берём дефолты из src.config (это “контракт приложения”)
    # - env используется только если ЯВНО задано (не “или os.getenv первым”)
    queue = os.getenv("RABBIT_EVENTS_QUEUE") if os.getenv("RABBIT_EVENTS_QUEUE") else RABBIT_EVENTS_QUEUE
    exchange = os.getenv("RABBIT_EVENTS_EXCHANGE") if os.getenv("RABBIT_EVENTS_EXCHANGE") else RABBIT_EVENTS_EXCHANGE
    routing_key = (
        os.getenv("RABBIT_EVENTS_ROUTING_KEY") if os.getenv("RABBIT_EVENTS_ROUTING_KEY") else RABBIT_EVENTS_ROUTING_KEY
    )

    logger.info("boot: consuming events exchange=%s queue=%s routing_key=%s", exchange, queue, routing_key)

    conn = _connect()
    ch = conn.channel()
    ch.basic_qos(prefetch_count=10)

    # topology
    ch.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
    ch.queue_declare(queue=queue, durable=True)
    ch.queue_bind(queue=queue, exchange=exchange, routing_key=routing_key)

    def on_message(channel, method, properties, body: bytes):
        headers = (properties.headers or {}) if properties else {}

        msg = _safe_json_loads(body)
        if msg is None:
            logger.warning("invalid json body, ack (drop)")
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        # rid/tid: headers -> body envelope -> pika properties
        rid = headers.get("x-request-id") or (msg.get("correlation_id") if isinstance(msg, dict) else None) or getattr(
            properties, "correlation_id", None
        )
        tid = headers.get("x-trace-id") or (msg.get("trace_id") if isinstance(msg, dict) else None)

        set_correlation(request_id=rid, trace_id=tid)

        db = SessionLocal()
        try:
            with db.begin():
                _handle_event(db, msg)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            logger.exception("events consumer failed, nack(requeue=true)")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        finally:
            db.close()

    ch.basic_consume(queue=queue, on_message_callback=on_message)
    ch.start_consuming()


if __name__ == "__main__":
    main()