from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List
from enum import Enum
from typing import Optional, List, Any


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


class VideoBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    visibility: Visibility = Field(default=Visibility.PRIVATE)


class VideoFormatBase(BaseModel):
    resolution: str
    width: int
    height: int
    codec: str
    bitrate_kbps: int
    file_size_bytes: int


class ProcessingTaskBase(BaseModel):
    task_type: ProcessingTaskType
    priority: int = Field(default=0, ge=0, le=10)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime
    storage_limit: int
    used_storage: int


class VideoFormatResponse(VideoFormatBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: int
    storage_path: str
    is_ready: bool
    created_at: datetime


class ProcessingTaskResponse(ProcessingTaskBase):
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
    hls_url: Optional[str] = None
    hls_ready: bool = False
    uploaded_at: datetime
    processed_at: Optional[datetime] = None

    # ✅ показываем текст ошибки (полезно для UI)
    error_message: Optional[str] = None

    owner: Optional[UserResponse] = None
    formats: List[VideoFormatResponse] = []
    processing_tasks: List[ProcessingTaskResponse] = []


class VideoCreate(VideoBase):
    pass


class VideoUploadCreate(BaseModel):
    title: str
    description: str | None = None
    visibility: Visibility = Visibility.PRIVATE
    filename: str
    file_size: int

    # ✅ идемпотентность prepare (uuid строкой от клиента)
    client_upload_id: str



class VideoUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    visibility: Optional[Visibility] = None
    is_blocked: Optional[bool] = None


class VideoUploadURL(BaseModel):
    upload_id: str
    upload_url: str
    video_id: int
    expires_at: datetime

    # ✅ ключ объекта в storage (для local = original_path, для S3 = object_key)
    object_key: str


class VideoUploadComplete(BaseModel):
    upload_id: str

    # ✅ подтверждение размера (клиент сообщает, сервер сверяет)
    size_bytes: int

    # ✅ подтверждение etag (для local можно md5; для S3 это ETag)
    etag: str | None = None

    # parts можно оставить как есть, если уже используется/планируется multipart
    parts: list[dict] | None = None



# ✅ Share link schemas (новое)
class ShareLinkResponse(BaseModel):
    video_id: int
    share_url: str


class RevokeShareResponse(BaseModel):
    video_id: int
    revoked: bool = True


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

#============== STATISTICS SCHEMAS =================

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


class VideoStreamInfo(BaseModel):
    """Информация для стриминга видео."""
    video_id: int
    title: str
    duration: float
    formats: list[Any]
    master_playlist_url: Optional[str] = None
    subtitles: list[dict] = []
