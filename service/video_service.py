# service/video_service.py
"""
Сервис для работы с видео: загрузка, управление, получение метаданных.
(Только API-логика; worker/processing логика вынесена в service/processing_service.py)
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session, joinedload

from db.models import (
    ProcessingTask,
    ProcessingTaskType,
    TaskStatus,
    User,
    Video,
    VideoFormat,
    VideoStatus,
    Visibility,
)
from errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from model.video import (
    UserStorageInfo,
    VideoCreate,
    VideoFilter,
    VideoFormatResponse,
    VideoPagination,
    VideoResponse,
    VideoStats,
    VideoStreamInfo,
    VideoUpdate,
    VideoUploadComplete,
    VideoUploadCreate,
    VideoUploadURL,
)

from service.correlation import get_request_id, get_trace_id
from service.events import VideoProcessRequestedPayload
from service.outbox import EVENT_VIDEO_PROCESS_REQUESTED, add_event
from service.paths import (
    original_path,
    hls_dir,
    thumbnail_dir,
    hls_public_master_url,
)
from service.storage_service import get_storage_provider
from service.video_status import transition_video_status


def build_hls_public_url(video_id: int) -> str:
    """Public HLS URL served by nginx/CDN: https://domain/hls/{video_id}/master.m3u8"""
    return hls_public_master_url(video_id)


# ========== VIDEO CRUD ==========

def create_video(
    db: Session,
    video_data: VideoCreate,
    user_id: int,
    original_filename: Optional[str] = None,
    file_size: Optional[int] = None,
) -> Video:
    """Создать запись о видео в БД."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found")

    if file_size:
        if user.used_storage + file_size > user.storage_limit:
            raise ValidationError("Storage limit exceeded")

    video = Video(
        title=video_data.title,
        description=video_data.description,
        visibility=video_data.visibility,
        owner_id=user_id,
        original_filename=original_filename,
        size_bytes=file_size,
        status=VideoStatus.UPLOADING,
    )

    db.add(video)
    db.commit()
    db.refresh(video)

    # Обновляем используемое хранилище
    if file_size:
        user.used_storage += file_size
        db.commit()

    return video


def get_video(
    db: Session,
    video_id: int,
    user_id: Optional[int] = None,
    share_token: Optional[str] = None,
) -> Video:
    """Получить видео по ID с проверкой прав доступа."""
    video = (
        db.query(Video)
        .options(
            joinedload(Video.owner),
            joinedload(Video.formats),
            joinedload(Video.processing_tasks),
        )
        .filter(Video.id == video_id)
        .first()
    )
    if not video:
        raise NotFoundError(f"Video {video_id} not found")

    if video.is_blocked:
        raise ForbiddenError("Video is blocked")

    # PRIVATE: только владелец
    if video.visibility == Visibility.PRIVATE:
        if user_id is None or video.owner_id != user_id:
            raise ForbiddenError("You don't have access to this video")

    # UNLISTED: владелец ИЛИ по share_token
    if video.visibility == Visibility.UNLISTED:
        if user_id is None or video.owner_id != user_id:
            if not share_token or not video.share_token or share_token != video.share_token:
                raise ForbiddenError("You don't have access to this video")

    return video


def get_videos(
    db: Session,
    filter_data: VideoFilter,
    pagination: VideoPagination,
    user_id: Optional[int] = None,
) -> Tuple[List[Video], int]:
    """
    Лента:
    - PUBLIC видео всем
    - плюс "мои" (любые visibility) если user_id задан
    - UNLISTED не показываем в общей ленте (только владельцу)
    """
    query = db.query(Video).options(
        joinedload(Video.owner),
        joinedload(Video.formats),
    )

    access_conditions = [Video.visibility == Visibility.PUBLIC]
    if user_id:
        access_conditions.append(Video.owner_id == user_id)
    query = query.filter(or_(*access_conditions))

    if user_id:
        query = query.filter(or_(Video.visibility != Visibility.UNLISTED, Video.owner_id == user_id))
    else:
        query = query.filter(Video.visibility != Visibility.UNLISTED)

    if filter_data.owner_id:
        query = query.filter(Video.owner_id == filter_data.owner_id)

    if filter_data.status:
        query = query.filter(Video.status == filter_data.status)

    if filter_data.visibility:
        query = query.filter(Video.visibility == filter_data.visibility)

    if filter_data.min_duration:
        query = query.filter(Video.duration >= filter_data.min_duration)

    if filter_data.max_duration:
        query = query.filter(Video.duration <= filter_data.max_duration)

    if filter_data.search_text:
        search = f"%{filter_data.search_text}%"
        query = query.filter(or_(Video.title.ilike(search), Video.description.ilike(search)))

    if filter_data.created_after:
        query = query.filter(Video.uploaded_at >= filter_data.created_after)

    if filter_data.created_before:
        query = query.filter(Video.uploaded_at <= filter_data.created_before)

    total = query.count()

    query = query.order_by(desc(Video.uploaded_at))
    query = query.offset((pagination.page - 1) * pagination.per_page).limit(pagination.per_page)

    return query.all(), total


def update_video(
    db: Session,
    video_id: int,
    update_data: VideoUpdate,
    user_id: int,
) -> Video:
    """Обновить метаданные видео (только пользовательские поля)."""
    video = get_video(db, video_id, user_id)

    if video.owner_id != user_id:
        raise ForbiddenError("You can only edit your own videos")

    update_dict = update_data.dict(exclude_unset=True)

    allowed_fields = {"title", "description", "visibility"}
    forbidden = set(update_dict.keys()) - allowed_fields
    if forbidden:
        raise ValidationError(f"Forbidden fields in update: {sorted(forbidden)}")

    for field, value in update_dict.items():
        setattr(video, field, value)

    db.commit()
    db.refresh(video)
    return video


def delete_video(db: Session, video_id: int, user_id: int) -> bool:
    """Удалить видео и все связанные артефакты (original, thumbnails, hls)."""
    video = get_video(db, video_id, user_id)

    if video.owner_id != user_id:
        raise ForbiddenError("You can only delete your own videos")

    # storage quota
    if video.size_bytes:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.used_storage = max(0, user.used_storage - video.size_bytes)

    storage = get_storage_provider()

    # original
    try:
        if video.original_path:
            storage.delete_file(video.original_path)
    except Exception:
        pass

    # thumbnails/v{video_id}/...
    try:
        storage.delete_dir(thumbnail_dir(video.id))
    except Exception:
        pass

    # hls/v{video_id}/...
    try:
        storage.delete_dir(hls_dir(video.id))
    except Exception:
        pass

    db.delete(video)
    db.commit()
    return True


def update_video_status(
    db: Session,
    video_id: int,
    status: VideoStatus,
    user_id: Optional[int] = None,
) -> Video:
    """API может менять статус только в рамках upload-части."""
    video = get_video(db, video_id, user_id)

    if status not in (VideoStatus.UPLOADING, VideoStatus.UPLOADED):
        raise ValidationError("Status change is not allowed from API")

    if status == VideoStatus.UPLOADED and video.status != VideoStatus.UPLOADING:
        raise ConflictError("Only UPLOADING -> UPLOADED is allowed")

    transition_video_status(video, status, actor="api")

    db.commit()
    db.refresh(video)
    return video


# ========== UPLOAD MANAGEMENT ==========

def prepare_video_upload(
    db: Session,
    upload_data: VideoUploadCreate,
    user_id: int,
    storage_backend: Any,
) -> VideoUploadURL:
    """
    Идемпотентный prepare:
    - client_upload_id приходит от клиента
    - повторный prepare возвращает тот же video/upload_id/object_key
    """
    if not upload_data.client_upload_id:
        raise ValidationError("client_upload_id is required")

    existing = (
        db.query(Video)
        .filter(
            Video.owner_id == user_id,
            Video.client_upload_id == upload_data.client_upload_id,
        )
        .one_or_none()
    )

    if existing:
        if not existing.original_path:
            existing.original_path = original_path(
                user_id=user_id,
                video_id=existing.id,
                filename=upload_data.filename,
            )
            db.commit()

        if not existing.upload_id:
            existing.upload_id = str(uuid.uuid4())
            db.commit()

        upload_url = storage_backend.generate_presigned_upload_url(
            object_name=existing.original_path,
            file_size=upload_data.file_size,
            expires_minutes=60,
        )

        return VideoUploadURL(
            upload_id=existing.upload_id,
            upload_url=upload_url,
            video_id=existing.id,
            expires_at=datetime.utcnow() + timedelta(minutes=55),
            object_key=existing.original_path,
        )

    video_create = VideoCreate(
        title=upload_data.title,
        description=upload_data.description,
        visibility=upload_data.visibility,
    )

    video = create_video(
        db=db,
        video_data=video_create,
        user_id=user_id,
        original_filename=upload_data.filename,
        file_size=upload_data.file_size,
    )

    storage_path = original_path(
        user_id=user_id,
        video_id=video.id,
        filename=upload_data.filename,
    )

    upload_id = str(uuid.uuid4())
    upload_url = storage_backend.generate_presigned_upload_url(
        object_name=storage_path,
        file_size=upload_data.file_size,
        expires_minutes=60,
    )

    video.original_path = storage_path
    video.client_upload_id = upload_data.client_upload_id
    video.upload_id = upload_id
    db.commit()

    return VideoUploadURL(
        upload_id=upload_id,
        upload_url=upload_url,
        video_id=video.id,
        expires_at=datetime.utcnow() + timedelta(minutes=55),
        object_key=storage_path,
    )


def complete_video_upload(
    db: Session,
    video_id: int,
    complete_data: VideoUploadComplete,
    user_id: int,
    storage_backend: Any,
) -> Video:
    """Завершить загрузку видео (идемпотентно)."""
    video = get_video(db, video_id, user_id)

    if video.owner_id != user_id:
        raise ForbiddenError("Access denied")

    if not video.upload_id or video.upload_id != complete_data.upload_id:
        raise ValidationError("Invalid upload_id")

    if video.status in (VideoStatus.UPLOADED, VideoStatus.PROCESSING, VideoStatus.READY, VideoStatus.FAILED):
        return video

    if not storage_backend.object_exists(video.original_path):
        raise ValidationError("Video file not found in storage")

    metadata = storage_backend.get_object_metadata(video.original_path)

    video.size_bytes = int(metadata.get("size", 0) or 0)
    video.mime_type = metadata.get("content_type") or "video/mp4"

    transition_video_status(video, VideoStatus.UPLOADED, actor="api")

    requested_payload = VideoProcessRequestedPayload(
        video_id=int(video.id),
        path=video.original_path,
    )

    add_event(
        db,
        event_type=EVENT_VIDEO_PROCESS_REQUESTED,
        payload=requested_payload.model_dump(),
        producer="api",
        correlation_id=get_request_id(),
        trace_id=get_trace_id(),
        aggregate_type="video",
        aggregate_id=str(video.id),
    )

    return video


# ========== VIDEO FORMATS ==========

def get_video_formats(db: Session, video_id: int, user_id: Optional[int] = None) -> List[VideoFormat]:
    video = get_video(db, video_id, user_id)
    return video.formats


def add_video_format(
    db: Session,
    video_id: int,
    format_data: Dict[str, Any],
    storage_path: str,
) -> VideoFormat:
    """Добавить новый формат видео (используется обработчиком)."""
    video = get_video(db, video_id)

    video_format = VideoFormat(
        video_id=video_id,
        resolution=format_data["resolution"],
        width=format_data["width"],
        height=format_data["height"],
        codec=format_data["codec"],
        bitrate_kbps=format_data["bitrate_kbps"],
        file_size_bytes=format_data["file_size_bytes"],
        storage_path=storage_path,
        is_ready=True,
    )

    db.add(video_format)
    db.commit()
    db.refresh(video_format)

    if video_format.file_size_bytes and video.owner:
        video.owner.used_storage += video_format.file_size_bytes
        db.commit()

    return video_format


# ========== PROCESSING TASKS ==========

def create_processing_task(
    db: Session,
    video_id: int,
    task_type: ProcessingTaskType,
    priority: int = 0,
) -> ProcessingTask:
    task = ProcessingTask(
        video_id=video_id,
        task_type=task_type,
        priority=priority,
        status=TaskStatus.PENDING,
    )

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_processing_task(db: Session, task_id: int, update_data: Dict[str, Any]) -> ProcessingTask:
    task = db.query(ProcessingTask).filter(ProcessingTask.id == task_id).first()
    if not task:
        raise NotFoundError(f"Processing task {task_id} not found")

    for field, value in update_data.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


# ========== STATISTICS ==========

def get_video_stats(db: Session, user_id: Optional[int] = None) -> VideoStats:
    query = db.query(Video)

    if user_id:
        query = query.filter(Video.owner_id == user_id)

    total_videos = query.count()
    total_size = query.with_entities(func.coalesce(func.sum(Video.size_bytes), 0)).scalar() or 0

    ready_videos = query.filter(Video.status == VideoStatus.READY).count()
    processing_videos = query.filter(Video.status == VideoStatus.PROCESSING).count()
    failed_videos = query.filter(Video.status == VideoStatus.FAILED).count()

    return VideoStats(
        total_videos=total_videos,
        total_size_bytes=total_size,
        ready_videos=ready_videos,
        processing_videos=processing_videos,
        failed_videos=failed_videos,
    )


def get_user_storage_info(db: Session, user_id: int) -> UserStorageInfo:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found")

    available = max(0, user.storage_limit - user.used_storage)
    used_percentage = (user.used_storage / user.storage_limit * 100) if user.storage_limit > 0 else 0

    return UserStorageInfo(
        used_storage=user.used_storage,
        storage_limit=user.storage_limit,
        used_percentage=used_percentage,
        available_bytes=available,
    )


# ========== STREAMING ==========

def get_video_stream_info(
    db: Session,
    video_id: int,
    user_id: Optional[int] = None,
    cdn_base_url: Optional[str] = None,
) -> VideoStreamInfo:
    video = get_video(db, video_id, user_id)

    if video.status != VideoStatus.READY:
        raise ValidationError("Video is not ready for streaming")

    ready_formats = [fmt for fmt in video.formats if fmt.is_ready]

    formats_with_urls: List[VideoFormatResponse] = []
    for fmt in ready_formats:
        if cdn_base_url:
            stream_url = f"{cdn_base_url}/{fmt.storage_path}"
        else:
            stream_url = f"/stream/{fmt.storage_path}"

        format_response = VideoFormatResponse.from_orm(fmt)
        setattr(format_response, "stream_url", stream_url)
        formats_with_urls.append(format_response)

    master_playlist_url = None
    if cdn_base_url and formats_with_urls:
        master_playlist_url = f"{cdn_base_url}/master/{video_id}/playlist.m3u8"

    return VideoStreamInfo(
        video_id=video.id,
        title=video.title,
        duration=video.duration or 0,
        formats=formats_with_urls,
        master_playlist_url=master_playlist_url,
        subtitles=[],
    )


# ========== SHARE LINKS ==========

def create_share_link(db: Session, video_id: int, user_id: int) -> str:
    """Создать/обновить share_token и сделать видео UNLISTED."""
    video = get_video(db, video_id, user_id=user_id)

    if video.owner_id != user_id:
        raise ForbiddenError("You can only share your own videos")

    token = uuid.uuid4().hex
    video.share_token = token
    video.visibility = Visibility.UNLISTED
    db.commit()
    db.refresh(video)
    return token


def revoke_share_link(db: Session, video_id: int, user_id: int) -> None:
    """Отключить доступ по ссылке."""
    video = get_video(db, video_id, user_id=user_id)

    if video.owner_id != user_id:
        raise ForbiddenError("You can only revoke share links for your own videos")

    video.share_token = None
    video.visibility = Visibility.PRIVATE
    db.commit()


def get_video_by_share_token(db: Session, token: str) -> Video:
    """Получить видео по токену (для просмотра без логина)."""
    video = (
        db.query(Video)
        .options(joinedload(Video.owner), joinedload(Video.formats), joinedload(Video.processing_tasks))
        .filter(Video.share_token == token)
        .first()
    )
    if not video:
        raise NotFoundError("Share link not found")

    if video.is_blocked:
        raise ForbiddenError("Video is blocked")

    if video.visibility != Visibility.UNLISTED:
        raise ForbiddenError("Share link is not active")

    return video


__all__ = [
    "create_video",
    "get_video",
    "get_videos",
    "update_video",
    "delete_video",
    "update_video_status",
    "prepare_video_upload",
    "complete_video_upload",
    "get_video_formats",
    "add_video_format",
    "create_processing_task",
    "update_processing_task",
    "get_video_stats",
    "get_user_storage_info",
    "get_video_stream_info",
    "create_share_link",
    "revoke_share_link",
    "get_video_by_share_token",
]