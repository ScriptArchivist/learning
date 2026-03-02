from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db_write
from db.models import Upload
from service.paths import original_path
from service.storage_service import get_storage_provider
from service.upload_service import create_upload, complete_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("/init")
def init_upload(
    video_id: int,
    owner_id: int,
    filename: str,
    db: Session = Depends(get_db_write),
):
    object_key = original_path(
        user_id=owner_id,
        video_id=video_id,
        filename=filename,
    )

    upload = create_upload(
        db=db,
        video_id=video_id,
        owner_id=owner_id,
        object_key=object_key,
    )

    return {
        "upload_id": upload.id,
        "object_key": upload.object_key,
    }


@router.post("/{upload_id}/file")
def upload_file(
    upload_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db_write),
):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(404)

    storage = get_storage_provider()
    storage.save_file(file, upload.object_key)

    return {"ok": True}


@router.post("/{upload_id}/complete")
def complete_upload_endpoint(
    upload_id: str,
    size: int,
    checksum: str | None = None,
    content_type: str | None = None,
    db: Session = Depends(get_db_write),
):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(404)

    storage = get_storage_provider()

    if not storage.file_exists(upload.object_key):
        raise HTTPException(400, "File not found")

    complete_upload(
        db=db,
        upload=upload,
        size=size,
        checksum=checksum,
        content_type=content_type,
    )

    return {"status": "completed"}