"""
Модели базы данных (SQLAlchemy) для видеоплатформы.
"""

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, 
    Boolean, Enum, BigInteger, Float, JSON, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum
from datetime import datetime

from .base import Base  # базовый класс

# ========== ENUMS ==========
class VideoStatus(str, enum.Enum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"

class Visibility(str, enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"

class ProcessingTaskType(str, enum.Enum):
    TRANSCODE = "transcode"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"

# ========== USER ==========
class User(Base):
    """Пользователь видеоплатформы."""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Квоты хранилища (в байтах)
    storage_limit: Mapped[int] = mapped_column(BigInteger, default=10*1024**3)  # 10GB
    used_storage: Mapped[int] = mapped_column(BigInteger, default=0)
    
    # Связи
    videos: Mapped[list["Video"]] = relationship("Video", back_populates="owner", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', email='{self.email}')>"

# ========== VIDEO ==========
class Video(Base):
    """Основная таблица видео."""
    __tablename__ = "videos"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    
    # Технические метаданные
    duration: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    
    # Статус и доступ
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus), 
        default=VideoStatus.UPLOADING, 
        index=True
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility), 
        default=Visibility.PRIVATE, 
        index=True
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Пути в объектном хранилище
    original_path: Mapped[str | None] = mapped_column(String(1000))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000))
    
    # Владелец
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), 
        index=True
    )
    
    # Даты
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Связи
    owner: Mapped["User"] = relationship("User", back_populates="videos")
    formats: Mapped[list["VideoFormat"]] = relationship(
        "VideoFormat", 
        back_populates="video", 
        cascade="all, delete-orphan"
    )
    processing_tasks: Mapped[list["ProcessingTask"]] = relationship(
        "ProcessingTask", 
        back_populates="video", 
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Video(id={self.id}, title='{self.title}', status='{self.status.value}')>"

# ========== VIDEO FORMAT ==========
class VideoFormat(Base):
    """Транскодированные версии видео."""
    __tablename__ = "video_formats"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), 
        index=True, 
        nullable=False
    )
    
    # Параметры качества
    resolution: Mapped[str] = mapped_column(String(20))  # "1080p", "720p"
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String(20))
    bitrate_kbps: Mapped[int] = mapped_column(Integer)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    
    # Путь в хранилище
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    
    # Статус
    is_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Связи
    video: Mapped["Video"] = relationship("Video", back_populates="formats")
    
    def __repr__(self) -> str:
        return f"<VideoFormat(id={self.id}, resolution='{self.resolution}', ready={self.is_ready})>"

# ========== PROCESSING TASK ==========
class ProcessingTask(Base):
    """Очередь задач обработки видео."""
    __tablename__ = "processing_tasks"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), 
        index=True, 
        nullable=False
    )
    
    # Тип задачи
    task_type: Mapped[ProcessingTaskType] = mapped_column(
        Enum(ProcessingTaskType), 
        nullable=False, 
        index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    
    # Идентификатор в Celery/RabbitMQ
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    
    # Статус
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), 
        default=TaskStatus.PENDING, 
        index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100%
    error_message: Mapped[str | None] = mapped_column(Text)
    
    # Временные метки
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Связи
    video: Mapped["Video"] = relationship("Video", back_populates="processing_tasks")
    
    def __repr__(self) -> str:
        return f"<ProcessingTask(id={self.id}, type='{self.task_type.value}', status='{self.status.value}')>"

# ========== EXPLORER (оставляем для обратной совместимости) ==========
class Explorer(Base):
    """
    Старая таблица 'explorers' (оставляем для обратной совместимости).
    """
    __tablename__ = "explorers"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default="", nullable=True)
    
    def __repr__(self) -> str:
        return f"<Explorer(id={self.id}, name='{self.name}', country='{self.country}')>"