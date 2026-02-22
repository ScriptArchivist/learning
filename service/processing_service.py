# service/processing_service.py
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import update, or_, and_

from db.database import SessionLocal
from db.models import Video, VideoStatus
from service.outbox import add_event, EVENT_VIDEO_PROCESS_COMPLETED
from service.events import VideoProcessCompletedPayload
from service.outbox import (
    add_event,
    EVENT_VIDEO_PROCESS_COMPLETED,
    EVENT_VIDEO_PROCESS_FAILED,
)


import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Video, VideoStatus
from service.video_status import transition_video_status


def claim_video_processing(video_id: int, lease_seconds: int) -> str | None:
    """
    Атомарно "захватывает" обработку видео на уровне БД.
    Возвращает lock_token если захват успешен, иначе None.

    Захват возможен если:
      - status = UPLOADED
      - или status = PROCESSING, но lease истёк (воркер умер)

    ВАЖНО (TASK A2):
      - переход в PROCESSING выполняется только через transition_video_status(..., actor="worker")
      - чтобы не было обхода state machine через прямой SQL update(status=...)
    """
    db: Session = SessionLocal()
    try:
        token = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=lease_seconds)

        # Берём строку под блокировку, чтобы "захват" был атомарным
        video = (
            db.execute(
                select(Video)
                .where(Video.id == video_id)
                .with_for_update()
            )
            .scalar_one_or_none()
        )

        if video is None:
            db.rollback()
            return None

        can_claim = (
            video.status == VideoStatus.UPLOADED
            or (
                video.status == VideoStatus.PROCESSING
                and video.processing_lock_expires_at is not None
                and video.processing_lock_expires_at < now
            )
        )

        if not can_claim:
            db.rollback()
            return None

        # ✅ State machine: только worker может переводить в PROCESSING
        # (если уже PROCESSING и lease истёк — статус остаётся PROCESSING, просто обновим lock)
        if video.status == VideoStatus.UPLOADED:
            transition_video_status(video, VideoStatus.PROCESSING, actor="worker")

        video.processing_lock_token = token
        video.processing_lock_expires_at = expires_at
        video.processing_started_at = now
        video.error_message = None

        db.commit()
        return token

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def complete_video_processing_with_lock(
    *,
    video_id: int,
    lock_token: str,
    processed_at: datetime,
    file_size: int,
    duration: float | None,
    width: int | None,
    height: int | None,
    thumbnail_path: str | None,
    mime_type: str | None,
    hls_master_key: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> bool:
    """
    Атомарно:
    - обновляет метаданные видео
    - переводит в READY
    - снимает lock
    - добавляет outbox-событие video.process.completed (в envelope)
    """

    db: Session = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(
                Video.id == video_id,
                Video.processing_lock_token == lock_token,
            )
            .one_or_none()
        )

        if not video:
            db.rollback()
            return False

        # --- обновление метаданных ---
        video.processed_at = processed_at
        video.size_bytes = file_size

        if duration is not None:
            video.duration = duration
        if width is not None:
            video.width = width
        if height is not None:
            video.height = height
        if thumbnail_path is not None:
            video.thumbnail_path = thumbnail_path
        if mime_type is not None:
            video.mime_type = mime_type

        # --- финальный статус ---
        from service.video_status import transition_video_status
        transition_video_status(video, VideoStatus.READY, actor="worker")
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        # --- строго типизированный payload ---
        completed_payload = VideoProcessCompletedPayload(
            video_id=video_id,
            # intentionally minimal v1.0
            # metadata можно будет добавить в v1.1 без breaking change
        )

        add_event(
            db,
            event_type=EVENT_VIDEO_PROCESS_COMPLETED,
            payload=completed_payload.model_dump(),
            producer="worker",
            correlation_id=correlation_id,
            trace_id=trace_id,
            aggregate_type="video",
            aggregate_id=str(video_id),
        )

        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Video, VideoStatus
from service.outbox import add_event, EVENT_VIDEO_PROCESS_FAILED
from service.events import VideoProcessFailedPayload


def fail_video_processing_with_lock(
    *,
    video_id: int,
    lock_token: str,
    error_message: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> bool:
    """
    Атомарно:
    - ставит FAILED
    - записывает error_message
    - очищает lock
    - добавляет outbox-событие video.process.failed (в envelope)
    """
    db: Session = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(
                Video.id == video_id,
                Video.processing_lock_token == lock_token,
            )
            .one_or_none()
        )

        if not video:
            db.rollback()
            return False


        transition_video_status(
            video,
            VideoStatus.FAILED,
            actor="worker",
            error_message=error_message,
        )
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        failed_payload = VideoProcessFailedPayload(
            video_id=video_id,
            error=error_message,
        )

        add_event(
            db,
            event_type=EVENT_VIDEO_PROCESS_FAILED,
            payload=failed_payload.model_dump(),
            producer="worker",
            correlation_id=correlation_id,
            trace_id=trace_id,
            aggregate_type="video",
            aggregate_id=str(video_id),
        )

        db.commit()
        return True

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()