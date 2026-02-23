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
    Берём lease/lock на обработку видео.

    Успех:
      - ставим processing_lock_token / expires_at / processing_started_at
      - делаем переход UPLOADED -> PROCESSING (actor=worker)
      - возвращаем lock_token

    Если видео уже в PROCESSING/READY/FAILED или lock активен — возвращаем None.
    """

    lock_token = str(uuid.uuid4())
    now = datetime.utcnow()
    expires_at = now + timedelta(seconds=lease_seconds)

    db = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(Video.id == video_id)
            .with_for_update()
            .one_or_none()
        )
        if not video:
            return None

        # Уже обработано или в процессе
        if video.status in (VideoStatus.PROCESSING, VideoStatus.READY, VideoStatus.FAILED):
            return None

        # Берём только UPLOADED
        if video.status != VideoStatus.UPLOADED:
            return None

        # Активный lock
        if (
            video.processing_lock_token
            and video.processing_lock_expires_at
            and video.processing_lock_expires_at > now
        ):
            return None

        video.processing_lock_token = lock_token
        video.processing_lock_expires_at = expires_at
        video.processing_started_at = now

        # 🔐 Строгий переход статуса
        transition_video_status(video, VideoStatus.PROCESSING, actor="worker")

        db.commit()
        return lock_token

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def complete_video_processing_with_lock(
    *,
    video_id: int,
    lock_token: str,
    processed_at,
    file_size: int | None,
    duration: float | None,
    width: int | None,
    height: int | None,
    thumbnail_path: str | None,
    mime_type: str | None,
    hls_master_key: str | None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
):
    """
    Завершение обработки по lock_token:
      - проверяем lock
      - пишем метаданные
      - PROCESSING -> READY
      - публикуем outbox event video.process.completed
      - чистим lock
    """

    db = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(Video.id == video_id)
            .with_for_update()
            .one_or_none()
        )
        if not video:
            return

        if not video.processing_lock_token or video.processing_lock_token != lock_token:
            return

        # ---- Обновляем метаданные ----
        if file_size is not None:
            video.size_bytes = file_size

        video.duration = duration
        video.width = width
        video.height = height
        video.thumbnail_path = thumbnail_path
        video.mime_type = mime_type or video.mime_type

        # ---- Статус строго через state machine ----
        transition_video_status(
            video,
            VideoStatus.READY,
            actor="worker",
            processed_at=processed_at,
        )

        # ---- Outbox event ----
        payload = VideoProcessCompletedPayload(
            video_id=video.id,
            duration=video.duration,
            width=video.width,
            height=video.height,
        )

        add_event(
            db=db,
            event_type=EVENT_VIDEO_PROCESS_COMPLETED,
            payload=payload.model_dump(),
            producer="worker",
            correlation_id=correlation_id,
            trace_id=trace_id,
            aggregate_type="video",
            aggregate_id=str(video.id),
        )

        # ---- Снимаем lock ----
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        db.commit()

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
):
    """
    Ошибка обработки:
      - проверяем lock
      - PROCESSING -> FAILED
      - сохраняем error_message
      - публикуем video.process.failed
      - чистим lock
    """

    db = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(Video.id == video_id)
            .with_for_update()
            .one_or_none()
        )
        if not video:
            return

        if not video.processing_lock_token or video.processing_lock_token != lock_token:
            return

        # ---- Статус через state machine ----
        transition_video_status(
            video,
            VideoStatus.FAILED,
            actor="worker",
            error_message=error_message,
        )

        # ---- Outbox event ----
        payload = VideoProcessFailedPayload(
            video_id=video.id,
            error_message=video.error_message,
        )

        add_event(
            db=db,
            event_type=EVENT_VIDEO_PROCESS_FAILED,
            payload=payload.model_dump(),
            producer="worker",
            correlation_id=correlation_id,
            trace_id=trace_id,
            aggregate_type="video",
            aggregate_id=str(video.id),
        )

        # ---- Снимаем lock ----
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()