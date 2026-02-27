"""
Модели базы данных (SQLAlchemy) для видеоплатформы.
"""

from datetime import datetime
import enum

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey,
    Boolean, Enum, BigInteger, Float, Index, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base


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
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    storage_limit: Mapped[int] = mapped_column(BigInteger, default=10 * 1024**3)
    used_storage: Mapped[int] = mapped_column(BigInteger, default=0)

    videos: Mapped[list["Video"]] = relationship(
        "Video", back_populates="owner", cascade="all, delete-orphan"
    )


# ========== VIDEO ==========
class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    original_filename: Mapped[str | None] = mapped_column(String(500))

    # ✅ Idempotency ключ от клиента (на prepare)
    client_upload_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # ✅ upload_id, который возвращаем в prepare (и проверяем в complete)
    upload_id: Mapped[str | None] = mapped_column(String(36), index=True)

    # ✅ etag (пока для local можно хранить md5; для S3 это будет S3 ETag)
    upload_etag: Mapped[str | None] = mapped_column(String(64))

    duration: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    # ВАЖНО: используем size_bytes как “реальный размер файла”
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(100))

    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus),
        default=VideoStatus.UPLOADING,
        index=True,
    )
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility),
        default=Visibility.PRIVATE,
        index=True,
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    original_path: Mapped[str | None] = mapped_column(String(1000))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000))

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ✅ lease/lock для идемпотентности обработки
    processing_lock_token: Mapped[str | None] = mapped_column(String(36), index=True)
    processing_lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ✅ текст ошибки обработки
    error_message: Mapped[str | None] = mapped_column(Text)

    # ✅ токен для UNLISTED
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    owner: Mapped["User"] = relationship("User", back_populates="videos")
    formats: Mapped[list["VideoFormat"]] = relationship(
        "VideoFormat",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    processing_tasks: Mapped[list["ProcessingTask"]] = relationship(
        "ProcessingTask",
        back_populates="video",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # существующий индекс
        Index("ix_videos_owner_status", "owner_id", "status"),

        # ✅ НОВЫЙ уникальный индекс для идемпотентности prepare
        Index(
            "ix_videos_owner_client_upload_id",
            "owner_id",
            "client_upload_id",
            unique=True,
        ),
    )


# ========== VIDEO FORMAT ==========
class VideoFormat(Base):
    __tablename__ = "video_formats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    resolution: Mapped[str] = mapped_column(String(20))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    codec: Mapped[str] = mapped_column(String(20))
    bitrate_kbps: Mapped[int] = mapped_column(Integer)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_ready: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    video: Mapped["Video"] = relationship("Video", back_populates="formats")


# ========== PROCESSING TASK ==========
class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True)

    task_type: Mapped[ProcessingTaskType] = mapped_column(Enum(ProcessingTaskType), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    video: Mapped["Video"] = relationship("Video", back_populates="processing_tasks")

    __table_args__ = (
        Index("ix_processing_tasks_video_status", "video_id", "status"),
    )


# ========== OUTBOX ==========
class OutboxStatus(str, enum.Enum):
    NEW = "new"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    aggregate_type: Mapped[str | None] = mapped_column(String(50), index=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(100), index=True)

    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # статус строкой (совпадает с миграцией)
    status: Mapped[str] = mapped_column(
        String(20),
        default=OutboxStatus.NEW.value,
        index=True,
        nullable=False,
    )

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text)

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        Index("ix_outbox_status_available", "status", "available_at"),
        Index("ix_outbox_status_locked", "status", "locked_at"),
    )


# ========== LIVE SESSIONS ==========
class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    stream_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    # status: "created" | "started" | "stopped" | "error"
    status: Mapped[str] = mapped_column(String(20), default="created", index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    error: Mapped[str | None] = mapped_column(Text)

    owner: Mapped["User"] = relationship("User")