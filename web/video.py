# web/video.py
"""
Эндпоинты для работы с видео: загрузка, просмотр, управление.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import logging

from db.database import get_db
from service.video_service import (
    create_video, get_video, get_videos, update_video, delete_video,
    prepare_video_upload, complete_video_upload, get_video_formats,
    get_video_stats, get_user_storage_info, get_video_stream_info,
    update_video_status
)
from model.video import (
    VideoCreate, VideoUpdate, VideoResponse, VideoFilter, VideoPagination,
    VideoUploadCreate, VideoUploadURL, VideoUploadComplete, VideoStats,
    UserStorageInfo, VideoStreamInfo, VideoStatus
)
from model.user import UserInDB
from errors import NotFoundError, ValidationError, ForbiddenError

# ИМПОРТ ЗАГЛУШКИ ВМЕСТО service.security
from service.security import get_current_user as get_current_user_stub

# Настройка логирования
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])

# ========== VIDEO CRUD ==========

@router.post("/", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db)
):
    """Создать новое видео (только метаданные)."""
    try:
        video = create_video(
            db=db,
            video_data=video_data,
            user_id=current_user["id"]
        )
        return video
    except Exception as e:
        logger.error(f"Error creating video: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/", response_model=dict)
def list_videos(
    status: Optional[VideoStatus] = Query(None, description="Фильтр по статусу"),
    visibility: Optional[str] = Query(None, description="Фильтр по видимости"),
    owner_id: Optional[int] = Query(None, description="Фильтр по владельцу"),
    min_duration: Optional[float] = Query(None, description="Минимальная длительность"),
    max_duration: Optional[float] = Query(None, description="Максимальная длительность"),
    search: Optional[str] = Query(None, description="Поиск по названию и описанию"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Количество на странице"),
    db: Session = Depends(get_db)
):
    """Получить список видео с фильтрацией."""
    try:
        # Создаем объекты фильтрации
        filter_data = VideoFilter(
            status=status,
            visibility=visibility,
            owner_id=owner_id,
            min_duration=min_duration,
            max_duration=max_duration,
            search_text=search
        )
        
        pagination = VideoPagination(page=page, per_page=per_page)
        
        # Заглушка user_id=1
        videos, total = get_videos(db, filter_data, pagination, user_id=1)
        
        # Подготавливаем ответ
        return {
            "items": [VideoResponse.from_orm(video) for video in videos],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        }
    except Exception as e:
        logger.error(f"Error listing videos: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/{video_id}", response_model=VideoResponse)
def get_video_endpoint(
    video_id: int,
    db: Session = Depends(get_db)
):
    """Получить информацию о видео."""
    try:
        video = get_video(db, video_id, user_id=1)  # заглушка
        return video
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))

@router.put("/{video_id}", response_model=VideoResponse)
def update_video_endpoint(
    video_id: int,
    update_data: VideoUpdate,
    db: Session = Depends(get_db)
):
    """Обновить метаданные видео."""
    try:
        video = update_video(db, video_id, update_data, user_id=1)  # заглушка
        return video
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating video {video_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_endpoint(
    video_id: int,
    db: Session = Depends(get_db)
):
    """Удалить видео."""
    try:
        delete_video(db, video_id, user_id=1)  # заглушка
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting video {video_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# Остальные функции (upload, streaming, stats) остаются без изменений
# ... [все что ниже из оригинального файла]