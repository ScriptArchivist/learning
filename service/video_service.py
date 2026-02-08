# service/video_service.py
"""
Сервис для работы с видео: загрузка, управление, получение метаданных.
"""

import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, asc, func, not_
from db.database import SessionLocal
from db.models import Video

from db.models import Video, VideoFormat, ProcessingTask, User, VideoStatus, Visibility, TaskStatus, ProcessingTaskType
from model.video import (
    VideoCreate, VideoUpdate, VideoResponse, VideoFilter, VideoPagination,
    VideoUploadCreate, VideoUploadURL, VideoUploadComplete, VideoStats,
    UserStorageInfo, VideoStreamInfo, VideoFormatResponse
)
from errors import NotFoundError, ValidationError, ForbiddenError, ConflictError

# ЗАГЛУШКИ ВМЕСТО ИМПОРТА ИЗ security.py
def get_current_user():
    """Заглушка для разработки."""
    return type('User', (), {'id': 1})()

def verify_storage_limit(user, file_size):
    """Заглушка для разработки."""
    return True

# ========== VIDEO CRUD ==========

def create_video(
    db: Session, 
    video_data: VideoCreate, 
    user_id: int,
    original_filename: Optional[str] = None,
    file_size: Optional[int] = None
) -> Video:
    """Создать запись о видео в БД."""
    # Проверяем лимит хранилища
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found")
    
    if file_size:
        if user.used_storage + file_size > user.storage_limit:
            raise ValidationError("Storage limit exceeded")
    
    # Создаем видео
    video = Video(
        title=video_data.title,
        description=video_data.description,
        visibility=video_data.visibility,
        owner_id=user_id,
        original_filename=original_filename,
        size_bytes=file_size,
        status=VideoStatus.UPLOADING
    )
    
    db.add(video)
    db.commit()
    db.refresh(video)
    
    # Обновляем используемое хранилище
    if file_size:
        user.used_storage += file_size
        db.commit()
    
    return video

def get_video(db: Session, video_id: int, user_id: Optional[int] = None) -> Video:
    """Получить видео по ID с проверкой прав доступа."""
    query = db.query(Video).options(
        joinedload(Video.owner),
        joinedload(Video.formats),
        joinedload(Video.processing_tasks)
    ).filter(Video.id == video_id)
    
    video = query.first()
    if not video:
        raise NotFoundError(f"Video {video_id} not found")
    
    # Проверка видимости
    if video.visibility == Visibility.PRIVATE and video.owner_id != user_id:
        raise ForbiddenError("You don't have access to this video")
    
    return video

def get_videos(
    db: Session,
    filter_data: VideoFilter,
    pagination: VideoPagination,
    user_id: Optional[int] = None
) -> Tuple[List[Video], int]:
    """Получить список видео с фильтрацией и пагинацией."""
    query = db.query(Video).options(
        joinedload(Video.owner),
        joinedload(Video.formats)
    )
    
    # Применяем фильтры
    if filter_data.owner_id:
        query = query.filter(Video.owner_id == filter_data.owner_id)
    elif user_id:
        # Если не указан owner_id, показываем только свои видео
        query = query.filter(Video.owner_id == user_id)
    
    if filter_data.status:
        query = query.filter(Video.status == filter_data.status)
    
    if filter_data.visibility:
        query = query.filter(Video.visibility == filter_data.visibility)
    else:
        # По умолчанию показываем только PUBLIC и свои
        if not filter_data.owner_id or filter_data.owner_id != user_id:
            query = query.filter(Video.visibility == Visibility.PUBLIC)
    
    if filter_data.min_duration:
        query = query.filter(Video.duration >= filter_data.min_duration)
    
    if filter_data.max_duration:
        query = query.filter(Video.duration <= filter_data.max_duration)
    
    if filter_data.search_text:
        search = f"%{filter_data.search_text}%"
        query = query.filter(
            or_(
                Video.title.ilike(search),
                Video.description.ilike(search)
            )
        )
    
    if filter_data.created_after:
        query = query.filter(Video.uploaded_at >= filter_data.created_after)
    
    if filter_data.created_before:
        query = query.filter(Video.uploaded_at <= filter_data.created_before)
    
    # Считаем общее количество
    total = query.count()
    
    # Пагинация и сортировка
    query = query.order_by(desc(Video.uploaded_at))
    query = query.offset((pagination.page - 1) * pagination.per_page)
    query = query.limit(pagination.per_page)
    
    videos = query.all()
    return videos, total

def update_video(
    db: Session, 
    video_id: int, 
    update_data: VideoUpdate, 
    user_id: int
) -> Video:
    """Обновить метаданные видео."""
    video = get_video(db, video_id, user_id)
    
    # Проверяем права
    if video.owner_id != user_id:
        raise ForbiddenError("You can only edit your own videos")
    
    # Обновляем поля
    update_dict = update_data.dict(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(video, field, value)
    
    db.commit()
    db.refresh(video)
    return video

def delete_video(db: Session, video_id: int, user_id: int) -> bool:
    """Удалить видео."""
    video = get_video(db, video_id, user_id)
    
    # Проверяем права
    if video.owner_id != user_id:
        raise ForbiddenError("You can only delete your own videos")
    
    # Возвращаем использованное хранилище
    if video.size_bytes:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.used_storage = max(0, user.used_storage - video.size_bytes)
    
    db.delete(video)
    db.commit()
    return True

def update_video_status(
    db: Session, 
    video_id: int, 
    status: VideoStatus,
    user_id: Optional[int] = None
) -> Video:
    """Обновить статус видео."""
    video = get_video(db, video_id, user_id)
    
    video.status = status
    if status == VideoStatus.READY:
        video.processed_at = datetime.utcnow()
    
    db.commit()
    db.refresh(video)
    return video

# ========== UPLOAD MANAGEMENT ==========

def prepare_video_upload(
    db: Session,
    upload_data: VideoUploadCreate,
    user_id: int,
    storage_backend: Any  # MinIO/S3 клиент
) -> VideoUploadURL:
    """Подготовить загрузку видео: создать запись и получить URL для загрузки."""
    # Создаем видео
    video_create = VideoCreate(
        title=upload_data.title,
        description=upload_data.description,
        visibility=upload_data.visibility
    )
    
    video = create_video(
        db=db,
        video_data=video_create,
        user_id=user_id,
        original_filename=upload_data.filename,
        file_size=upload_data.file_size
    )
    
    # Генерируем уникальный путь в хранилище
    file_ext = os.path.splitext(upload_data.filename)[1]
    storage_path = f"original/{user_id}/{video.id}/{uuid.uuid4()}{file_ext}"
    
    # Получаем URL для загрузки (presigned URL для S3/MinIO)
    upload_id = str(uuid.uuid4())
    upload_url = storage_backend.generate_presigned_upload_url(
        object_name=storage_path,
        file_size=upload_data.file_size,
        expires_minutes=60
    )
    
    # Сохраняем путь к видео
    video.original_path = storage_path
    db.commit()
    
    return VideoUploadURL(
        upload_id=upload_id,
        upload_url=upload_url,
        video_id=video.id,
        expires_at=datetime.utcnow() + timedelta(minutes=55)
    )

def complete_video_upload(
    db: Session,
    video_id: int,
    complete_data: VideoUploadComplete,
    user_id: int,
    storage_backend: Any
) -> Video:
    """Завершить загрузку видео."""
    video = get_video(db, video_id, user_id)
    
    # Проверяем права
    if video.owner_id != user_id:
        raise ForbiddenError("Access denied")
    
    # Проверяем, что файл действительно загружен
    if not storage_backend.object_exists(video.original_path):
        raise ValidationError("Video file not found in storage")
    
    # Получаем метаданные файла
    metadata = storage_backend.get_object_metadata(video.original_path)
    video.size_bytes = metadata.get('size', 0)
    video.mime_type = metadata.get('content_type', 'video/mp4')
    
    # Обновляем статус
    video.status = VideoStatus.UPLOADED
    
    # Создаем задачу на обработку
    processing_task = ProcessingTask(
        video_id=video_id,
        task_type=ProcessingTaskType.METADATA,
        priority=5
    )
    db.add(processing_task)
    
    db.commit()
    
    # TODO: Отправить задачу в очередь обработки
    # celery_app.send_task('process_video_metadata', args=[video.id])
    
    return video

# ========== VIDEO FORMATS ==========

def get_video_formats(db: Session, video_id: int, user_id: Optional[int] = None) -> List[VideoFormat]:
    """Получить доступные форматы видео."""
    video = get_video(db, video_id, user_id)
    return video.formats

def add_video_format(
    db: Session,
    video_id: int,
    format_data: Dict[str, Any],
    storage_path: str
) -> VideoFormat:
    """Добавить новый формат видео (используется обработчиком)."""
    video = get_video(db, video_id)  # Без проверки пользователя
    
    video_format = VideoFormat(
        video_id=video_id,
        resolution=format_data['resolution'],
        width=format_data['width'],
        height=format_data['height'],
        codec=format_data['codec'],
        bitrate_kbps=format_data['bitrate_kbps'],
        file_size_bytes=format_data['file_size_bytes'],
        storage_path=storage_path,
        is_ready=True
    )
    
    db.add(video_format)
    db.commit()
    db.refresh(video_format)
    
    # Обновляем общий размер хранилища пользователя
    if video_format.file_size_bytes and video.owner:
        video.owner.used_storage += video_format.file_size_bytes
        db.commit()
    
    return video_format

# ========== PROCESSING TASKS ==========

def create_processing_task(
    db: Session,
    video_id: int,
    task_type: ProcessingTaskType,
    priority: int = 0
) -> ProcessingTask:
    """Создать задачу обработки."""
    task = ProcessingTask(
        video_id=video_id,
        task_type=task_type,
        priority=priority,
        status=TaskStatus.PENDING
    )
    
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def update_processing_task(
    db: Session,
    task_id: int,
    update_data: Dict[str, Any]
) -> ProcessingTask:
    """Обновить статус задачи обработки."""
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
    """Получить статистику по видео."""
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
        failed_videos=failed_videos
    )

def get_user_storage_info(db: Session, user_id: int) -> UserStorageInfo:
    """Получить информацию о хранилище пользователя."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found")
    
    available = max(0, user.storage_limit - user.used_storage)
    used_percentage = (user.used_storage / user.storage_limit * 100) if user.storage_limit > 0 else 0
    
    return UserStorageInfo(
        used_storage=user.used_storage,
        storage_limit=user.storage_limit,
        used_percentage=used_percentage,
        available_bytes=available
    )

# ========== STREAMING ==========

def get_video_stream_info(
    db: Session, 
    video_id: int, 
    user_id: Optional[int] = None,
    cdn_base_url: Optional[str] = None
) -> VideoStreamInfo:
    """Получить информацию для стриминга видео."""
    video = get_video(db, video_id, user_id)
    
    # Проверяем, что видео готово
    if video.status != VideoStatus.READY:
        raise ValidationError("Video is not ready for streaming")
    
    # Фильтруем готовые форматы
    ready_formats = [fmt for fmt in video.formats if fmt.is_ready]
    
    # Генерируем URL для стриминга
    formats_with_urls = []
    for fmt in ready_formats:
        if cdn_base_url:
            stream_url = f"{cdn_base_url}/{fmt.storage_path}"
        else:
            # Локальный URL для разработки
            stream_url = f"/stream/{fmt.storage_path}"
        
        format_response = VideoFormatResponse.from_orm(fmt)
        # Добавляем URL в ответ (не хранится в БД)
        setattr(format_response, 'stream_url', stream_url)
        formats_with_urls.append(format_response)
    
    # Генерируем master playlist для HLS/DASH
    master_playlist_url = None
    if cdn_base_url and formats_with_urls:
        master_playlist_url = f"{cdn_base_url}/master/{video_id}/playlist.m3u8"
    
    return VideoStreamInfo(
        video_id=video.id,
        title=video.title,
        duration=video.duration or 0,
        formats=formats_with_urls,
        master_playlist_url=master_playlist_url,
        subtitles=[]  # TODO: добавить субтитры
    )

# ========== пбликуем задачу и ставим статус QUEUED ==========

def set_video_status(video_id: int, status: str, error_message: str | None = None):
    db = SessionLocal()
    try:
        v = db.query(Video).filter(Video.id == video_id).one()
        v.status = status
        v.error_message = error_message
        db.commit()
    finally:
        db.close()
        
# ========== Сервисная функция для записи результата ==========

def set_video_processed_info(video_id: int, processed_at, file_size: int):
    db = SessionLocal()
    try:
        v = db.query(Video).filter(Video.id == video_id).one()
        v.processed_at = processed_at
        v.file_size = file_size
        db.commit()
    finally:
        db.close()

# Экспортируемые функции
__all__ = [
    # CRUD
    "create_video",
    "get_video", 
    "get_videos",
    "update_video",
    "delete_video",
    "update_video_status",
    
    # Upload
    "prepare_video_upload",
    "complete_video_upload",
    
    # Formats
    "get_video_formats",
    "add_video_format",
    
    # Processing tasks
    "create_processing_task",
    "update_processing_task",
    
    # Statistics
    "get_video_stats",
    "get_user_storage_info",
    
    # Streaming
    "get_video_stream_info",
]