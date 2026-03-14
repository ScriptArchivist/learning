# web/video.py
"""
Video API (metadata & playback) + Backward-compatible upload + share endpoints.

Этап 3 (video-api для Flutter):
- POST /videos
- GET /videos/{id}
- GET /videos
- GET /videos/{id}/playback
- PATCH /videos/{id}
- DELETE /videos/{id}

Совместимость (пока upload-service не стал единственным входом):
- POST /videos/upload/prepare
- POST /videos/{id}/upload/direct
- POST /videos/{id}/upload/complete

Также совместимость для тестов:
- POST /videos/{id}/share
- POST /videos/{id}/share/revoke
- GET  /videos/shared/{token}

Файловая раздача (mp4/hls/thumb) и watch — НЕ часть video-api на этом этапе.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from db.database import get_db_read, get_db_write
from errors import ForbiddenError, NotFoundError, ValidationError
from model.user import UserInDB
from model.video import (
    RevokeShareResponse,
    ShareLinkResponse,
    VideoCreate,
    VideoFilter,
    VideoPagination,
    VideoStatus,
    VideoUpdate,
    VideoUploadComplete,
    VideoUploadCreate,
    VideoUploadURL,
    Visibility,
)
from model.video_contract import VideoDetailDTO, VideoListResponse
from service.security import get_current_user as get_current_user_stub
from service.storage_service import get_storage_provider
from service.video_presenter import to_detail, to_list_item
from service.video_service import (
    complete_video_upload,
    create_share_link,
    create_video,
    delete_video,
    get_video,
    get_video_by_share_token,
    get_videos,
    prepare_video_upload,
    revoke_share_link,
    update_video,
)
from service.video_status import VideoStatusTransitionError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/videos", tags=["videos"], redirect_slashes=False)


# -------------------- Upload backend adapter (local) --------------------


class StorageBackendAdapter:
    """
    Adapter, который предоставляет минимальный контракт для service.video_service:
    - object_exists
    - get_object_metadata
    - generate_presigned_upload_url (для local возвращаем заглушку, а URL перезапишем в endpoint)
    """

    def __init__(self, storage):
        self.storage = storage

    def generate_presigned_upload_url(self, object_name: str, file_size: int, expires_minutes: int = 60) -> str:
        # local: upload идёт через API endpoint /upload/direct
        return "/api/v1/videos/{video_id}/upload/direct"

    def object_exists(self, path: str) -> bool:
        return self.storage.file_exists(path)

    def get_object_metadata(self, path: str) -> dict:
        size = self.storage.get_file_size(path)
        content_type, _ = mimetypes.guess_type(path)
        etag = None
        try:
            with self.storage.get_file(path) as f:
                h = hashlib.md5()
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
                etag = h.hexdigest()
        except Exception:
            etag = None
        return {"size": size, "content_type": content_type or "video/mp4", "etag": etag}


# -------------------- CRUD (metadata) --------------------


@router.post("", response_model=VideoDetailDTO, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=VideoDetailDTO, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        video = create_video(db=db, video_data=video_data, user_id=current_user["id"])
        return to_detail(video)
    except (ValidationError, ForbiddenError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=VideoListResponse)
@router.get("/", response_model=VideoListResponse)
def list_videos_endpoint(
    status: Optional[VideoStatus] = Query(None),
    visibility: Optional[Visibility] = Query(None),
    owner_id: Optional[int] = Query(None),
    min_duration: Optional[float] = Query(None),
    max_duration: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    filter_data = VideoFilter(
        status=status,
        visibility=visibility,
        owner_id=owner_id,
        min_duration=min_duration,
        max_duration=max_duration,
        search_text=search,
    )
    pagination = VideoPagination(page=page, per_page=per_page)

    videos, total = get_videos(db, filter_data, pagination, user_id=current_user["id"])
    return VideoListResponse(
        items=[to_list_item(v) for v in videos],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get("/{video_id}", response_model=VideoDetailDTO)
def get_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        return to_detail(video)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{video_id}", response_model=VideoDetailDTO)
def update_video_endpoint(
    video_id: int,
    payload: VideoUpdate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        video = update_video(
            db=db,
            video_id=video_id,
            update_data=payload,
            user_id=current_user["id"],
        )
        return to_detail(video)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        delete_video(
            db=db,
            video_id=video_id,
            user_id=current_user["id"],
        )
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# -------------------- Playback --------------------


@router.get("/{video_id}/playback")
def get_video_playback(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        item = to_list_item(video)
        return {"video_id": video.id, "hls_ready": item.hls_ready, "hls_url": item.hls_url}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# -------------------- Upload flow (compat for tests/local) --------------------


@router.post("/upload/prepare", response_model=VideoUploadURL)
def upload_prepare_endpoint(
    payload: VideoUploadCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    storage = get_storage_provider()
    backend = StorageBackendAdapter(storage)

    try:
        result = prepare_video_upload(
            db=db,
            upload_data=payload,
            user_id=current_user["id"],
            storage_backend=backend,
        )
        # local: direct upload через web
        result.upload_url = f"/api/v1/videos/{result.video_id}/upload/direct"
        return result

    except (ValidationError, NotFoundError, ForbiddenError, VideoStatusTransitionError) as e:
        db.rollback()
        code = 400
        if isinstance(e, NotFoundError):
            code = 404
        elif isinstance(e, ForbiddenError):
            code = 403
        elif isinstance(e, VideoStatusTransitionError):
            code = 409
        raise HTTPException(status_code=code, detail=str(e))


@router.post("/{video_id}/upload/direct")
def upload_direct_endpoint(
    video_id: int,
    file: UploadFile = File(...),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    video = get_video(db, video_id, user_id=current_user["id"])

    if video.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    if video.status != VideoStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="Upload is not allowed in this status")
    if not video.original_path:
        raise HTTPException(status_code=400, detail="original_path is empty. Call /upload/prepare first.")

    storage = get_storage_provider()
    try:
        try:
            file.file.seek(0)
        except Exception:
            pass
        storage.save_file(file, video.original_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {type(e).__name__}: {e}")

    return {"ok": True, "video_id": video_id, "path": video.original_path}


@router.post("/{video_id}/upload/complete", response_model=VideoDetailDTO)
def upload_complete_endpoint(
    video_id: int,
    payload: VideoUploadComplete,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    storage = get_storage_provider()
    backend = StorageBackendAdapter(storage)

    try:
        video = complete_video_upload(
            db=db,
            video_id=video_id,
            complete_data=payload,
            user_id=current_user["id"],
            storage_backend=backend,
        )
        db.commit()
        db.refresh(video)
        return to_detail(video)

    except (ValidationError, NotFoundError, ForbiddenError, VideoStatusTransitionError) as e:
        db.rollback()
        code = 400
        if isinstance(e, NotFoundError):
            code = 404
        elif isinstance(e, ForbiddenError):
            code = 403
        elif isinstance(e, VideoStatusTransitionError):
            code = 409
        raise HTTPException(status_code=code, detail=str(e))


# -------------------- Share (compat for tests) --------------------


@router.post("/{video_id}/share", response_model=ShareLinkResponse)
def create_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    """
    Возвращаем share_url как относительный путь (как было раньше).
    """
    try:
        token = create_share_link(db, video_id=video_id, user_id=current_user["id"])
        return ShareLinkResponse(video_id=video_id, share_url=f"/api/v1/videos/shared/{token}")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{video_id}/share/revoke", response_model=RevokeShareResponse)
def revoke_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        revoke_share_link(db, video_id=video_id, user_id=current_user["id"])
        return RevokeShareResponse(video_id=video_id, revoked=True)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/shared/{token}", response_model=VideoDetailDTO)
def get_shared_video_endpoint(
    token: str,
    db: Session = Depends(get_db_read),
):
    """
    Публичная карточка по share token (UNLISTED).
    """
    try:
        video = get_video_by_share_token(db, token)
        return to_detail(video, shared_token=token)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))