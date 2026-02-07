# model/video.py
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List, Any
from enum import Enum
from sqlalchemy import Column, String

# ========== ENUMS ==========
class VideoStatus(str, Enum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class Visibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"

class ProcessingTaskType(str, Enum):
    TRANSCODE = "transcode"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"

# ========== BASE SCHEMAS ==========
class VideoBase(BaseModel):
    """Базовая схема видео."""
    title: str = Field(..., min_length=1, max_length=200, examples=["Мое первое видео"])
    description: Optional[str] = Field(None, max_length=5000, examples=["Описание видео"])
    visibility: Visibility = Field(default=Visibility.PRIVATE, examples=["public"])

class VideoFormatBase(BaseModel):
    """Базовая схема формата видео."""
    resolution: str = Field(..., examples=["1080p"])
    width: int = Field(..., gt=0, examples=[1920])
    height: int = Field(..., gt=0, examples=[1080])
    codec: str = Field(..., examples=["h264"])
    bitrate_kbps: int = Field(..., gt=0, examples=[5000])
    file_size_bytes: int = Field(..., gt=0, examples=[10485760])

class ProcessingTaskBase(BaseModel):
    """Базовая схема задачи обработки."""
    task_type: ProcessingTaskType = Field(..., examples=["transcode"])
    priority: int = Field(default=0, ge=0, le=10, examples=[5])

# ========== RESPONSE SCHEMAS ==========
class UserResponse(BaseModel):
    """Схема ответа для пользователя."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime
    storage_limit: int
    used_storage: int

class VideoFormatResponse(VideoFormatBase):
    """Схема ответа для формата видео."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    video_id: int
    storage_path: str
    is_ready: bool
    created_at: datetime

class ProcessingTaskResponse(ProcessingTaskBase):
    """Схема ответа для задачи обработки."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    video_id: int
    status: TaskStatus
    progress: int
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class VideoResponse(VideoBase):
    """Полная схема ответа для видео."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    owner_id: int
    original_filename: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    status: VideoStatus
    is_blocked: bool
    original_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    
    # Опциональные связи (загружаются при необходимости)
    owner: Optional[UserResponse] = None
    formats: List[VideoFormatResponse] = []
    processing_tasks: List[ProcessingTaskResponse] = []

# ========== CREATE SCHEMAS ==========
class VideoCreate(VideoBase):
    """Схема для создания видео."""
    pass

class VideoUploadCreate(BaseModel):
    """Схема для начала загрузки видео."""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Visibility = Visibility.PRIVATE
    filename: str = Field(..., examples=["my_video.mp4"])
    file_size: int = Field(..., gt=0, examples=[10485760])

class ProcessingTaskCreate(ProcessingTaskBase):
    """Схема для создания задачи обработки."""
    video_id: int

# ========== UPDATE SCHEMAS ==========
class VideoUpdate(BaseModel):
    """Схема для обновления видео."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    visibility: Optional[Visibility] = None
    is_blocked: Optional[bool] = None

class VideoStatusUpdate(BaseModel):
    """Схема для обновления статуса видео."""
    status: VideoStatus

class ProcessingTaskUpdate(BaseModel):
    """Схема для обновления задачи обработки."""
    status: Optional[TaskStatus] = None
    progress: Optional[int] = Field(None, ge=0, le=100)
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None

# ========== QUERY/FILTER SCHEMAS ==========
class VideoFilter(BaseModel):
    """Схема для фильтрации видео."""
    status: Optional[VideoStatus] = None
    visibility: Optional[Visibility] = None
    owner_id: Optional[int] = None
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    search_text: Optional[str] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None

class VideoPagination(BaseModel):
    """Схема для пагинации видео."""
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)

# ========== STATISTICS SCHEMAS ==========
class VideoStats(BaseModel):
    """Статистика по видео."""
    total_videos: int
    total_size_bytes: int
    ready_videos: int
    processing_videos: int
    failed_videos: int

class UserStorageInfo(BaseModel):
    """Информация о хранилище пользователя."""
    used_storage: int
    storage_limit: int
    used_percentage: float
    available_bytes: int

# ========== UPLOAD SCHEMAS ==========
class VideoUploadURL(BaseModel):
    """Схема с URL для загрузки видео."""
    upload_id: str
    upload_url: str
    video_id: int
    expires_at: datetime

class VideoUploadComplete(BaseModel):
    """Схема для завершения загрузки."""
    upload_id: str
    parts: Optional[List[dict]] = None  # Для multipart upload

# ========== STREAMING SCHEMAS ==========
class VideoStreamInfo(BaseModel):
    """Информация для стриминга видео."""
    video_id: int
    title: str
    duration: float
    formats: List[VideoFormatResponse]
    master_playlist_url: Optional[str] = None
    subtitles: List[dict] = []

# ========== VIDEO STATES IN DATABASE ==========
status = Column(String, nullable=False, default="UPLOADED")
error_message = Column(String, nullable=True)