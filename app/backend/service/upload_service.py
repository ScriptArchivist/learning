import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from db.models import OutboxEvent, OutboxStatus, Upload, UploadStatus, Video, VideoStatus
from service.correlation import get_request_id, get_trace_id
from service.events import VideoProcessRequestedPayload
from service.outbox import EVENT_VIDEO_PROCESS_REQUESTED, add_event
from service.video_status import transition_video_status

EVENT_UPLOAD_COMPLETED = "upload.completed"


def create_upload(
    db: Session,
    *,
    video_id: int,
    owner_id: int,
    object_key: str,
) -> Upload:
    upload = Upload(
        id=str(uuid.uuid4()),
        video_id=video_id,
        owner_id=owner_id,
        object_key=object_key,
        status=UploadStatus.INITIATED,
    )

    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def _has_process_request_event(db: Session, video_id: int) -> bool:
    existing = (
        db.query(OutboxEvent.id)
        .filter(
            OutboxEvent.event_type == EVENT_VIDEO_PROCESS_REQUESTED,
            OutboxEvent.aggregate_type == "video",
            OutboxEvent.aggregate_id == str(video_id),
            OutboxEvent.status.in_(
                [
                    OutboxStatus.NEW.value,
                    OutboxStatus.PROCESSING.value,
                    OutboxStatus.PUBLISHED.value,
                ]
            ),
        )
        .first()
    )
    return existing is not None


def complete_upload(
    db: Session,
    *,
    upload: Upload,
    size: int,
    checksum: str | None,
    content_type: str | None,
):
    upload.size = size
    upload.checksum = checksum
    upload.content_type = content_type
    upload.status = UploadStatus.COMPLETED
    upload.completed_at = datetime.utcnow()

    video = (
        db.query(Video)
        .filter(Video.id == upload.video_id)
        .with_for_update()
        .one_or_none()
    )
    if not video:
        raise ValueError(f"Video {upload.video_id} not found for upload {upload.id}")

    # Синхронизируем Video из Upload: это критично для worker
    video.original_path = upload.object_key
    video.size_bytes = size
    if content_type:
        video.mime_type = content_type

    # upload.completed оставляем для совместимости
    add_event(
        db=db,
        event_type=EVENT_UPLOAD_COMPLETED,
        payload={
            "upload_id": upload.id,
            "video_id": upload.video_id,
            "object_key": upload.object_key,
            "size": upload.size,
            "size_bytes": upload.size,
            "checksum": upload.checksum,
            "content_type": upload.content_type,
        },
        producer="upload-service",
        aggregate_type="upload",
        aggregate_id=upload.id,
    )

    should_enqueue_processing = False

    if video.status == VideoStatus.UPLOADING:
        transition_video_status(video, VideoStatus.UPLOADED, actor="api")
        should_enqueue_processing = True
    elif video.status == VideoStatus.UPLOADED:
        # Важно для повторного /complete после старого buggy flow:
        # если видео уже uploaded, но event ещё не создавался — создаём его сейчас.
        should_enqueue_processing = not _has_process_request_event(db, video.id)
    elif video.status in (VideoStatus.PROCESSING, VideoStatus.READY, VideoStatus.FAILED):
        should_enqueue_processing = False

    if should_enqueue_processing:
        job_id = str(uuid.uuid4())
        requested_payload = VideoProcessRequestedPayload(
            job_id=job_id,
            video_id=int(video.id),
            input_key=video.original_path,
            output_prefix=f"hls/v{video.id}",
            attempt=1,
        )

        add_event(
            db=db,
            event_type=EVENT_VIDEO_PROCESS_REQUESTED,
            payload=requested_payload.model_dump(),
            producer="upload-service",
            correlation_id=get_request_id(),
            trace_id=get_trace_id(),
            aggregate_type="video",
            aggregate_id=str(video.id),
        )

    db.commit()