# service/processing_service.py
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import update, or_, and_

from db.database import SessionLocal
from db.models import Video, VideoStatus
from service.outbox import (
    add_event,
    EVENT_VIDEO_PROCESS_COMPLETED,
    EVENT_VIDEO_PROCESS_FAILED,
)


def claim_video_processing(video_id: int, lease_seconds: int) -> str | None:
    """
    Атомарно "захватывает" обработку видео на уровне БД.
    Возвращает lock_token если захват успешен, иначе None.

    Захват возможен если:
      - status = UPLOADED
      - или status = PROCESSING, но lease истёк (воркер умер)
    """
    db: Session = SessionLocal()
    try:
        token = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=lease_seconds)

        stmt = (
            update(Video)
            .where(
                Video.id == video_id,
                or_(
                    Video.status == VideoStatus.UPLOADED,
                    and_(
                        Video.status == VideoStatus.PROCESSING,
                        Video.processing_lock_expires_at.isnot(None),
                        Video.processing_lock_expires_at < now,
                    ),
                ),
            )
            .values(
                status=VideoStatus.PROCESSING,
                processing_lock_token=token,
                processing_lock_expires_at=expires_at,
                processing_started_at=now,
                error_message=None,
            )
        )

        res = db.execute(stmt)
        db.commit()
        return token if res.rowcount == 1 else None
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
) -> bool:
    """
    Атомарно:
    - обновляет метаданные
    - ставит READY
    - очищает lock
    - добавляет outbox event video.process.completed
    """
    db: Session = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(Video.id == video_id, Video.processing_lock_token == lock_token)
            .one_or_none()
        )

        if not video:
            db.rollback()
            return False

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

        video.status = VideoStatus.READY
        video.error_message = None
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        add_event(
            db,
            event_type=EVENT_VIDEO_PROCESS_COMPLETED,
            payload={
                "video_id": video_id,
                "status": VideoStatus.READY.value,
                "thumbnail_path": thumbnail_path,
                "hls_master_path": hls_master_key,
                "processed_at": processed_at.isoformat(),
                "duration": duration,
                "width": width,
                "height": height,
                "size_bytes": file_size,
            },
            producer="processing",
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


def fail_video_processing_with_lock(
    *,
    video_id: int,
    lock_token: str,
    error_message: str,
) -> bool:
    """
    Атомарно:
    - ставит FAILED
    - очищает lock
    - добавляет outbox event video.process.failed
    """
    db: Session = SessionLocal()
    try:
        video = (
            db.query(Video)
            .filter(Video.id == video_id, Video.processing_lock_token == lock_token)
            .one_or_none()
        )

        if not video:
            db.rollback()
            return False

        video.status = VideoStatus.FAILED
        video.error_message = error_message
        video.processing_lock_token = None
        video.processing_lock_expires_at = None

        add_event(
            db,
            event_type=EVENT_VIDEO_PROCESS_FAILED,
            payload={
                "video_id": video_id,
                "status": VideoStatus.FAILED.value,
                "error_message": error_message,
            },
            producer="processing",
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