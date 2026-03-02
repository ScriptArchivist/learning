import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from db.models import Upload, UploadStatus
from service.outbox import add_event

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

    add_event(
        db=db,
        event_type=EVENT_UPLOAD_COMPLETED,
        payload={
            "upload_id": upload.id,
            "video_id": upload.video_id,
            "object_key": upload.object_key,
            "size": upload.size,
            "checksum": upload.checksum,
            "content_type": upload.content_type,
        },
        producer="upload-service",
        aggregate_type="upload",
        aggregate_id=upload.id,
    )

    db.commit()