# web/video.py
"""
Эндпоинты для работы с видео: загрузка, просмотр, управление.
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import Optional
import logging
import mimetypes
from service.broker import publish_video_process
from service.video_service import set_video_status 

from db.database import get_db
from service.video_service import (
    create_video, get_video, get_videos, update_video, delete_video,
    prepare_video_upload, complete_video_upload
)
from model.video import (
    VideoCreate, VideoUpdate, VideoResponse, VideoFilter, VideoPagination,
    VideoUploadCreate, VideoUploadURL, VideoUploadComplete, VideoStatus
)
from model.user import UserInDB
from errors import NotFoundError, ValidationError, ForbiddenError

# Заглушка авторизации
from service.security import get_current_user as get_current_user_stub

from service.storage_service import get_storage_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"])


# ===================== Адаптер для video_service =====================
class StorageBackendAdapter:
    """
    Адаптер, чтобы service.video_service мог работать с твоим StorageProvider (LocalStorage/S3Storage).
    В video_service ожидаются методы:
      - generate_presigned_upload_url(object_name, file_size, expires_minutes)
      - object_exists(path)
      - get_object_metadata(path)
    """

    def __init__(self, storage):
        self.storage = storage

    def generate_presigned_upload_url(self, object_name: str, file_size: int, expires_minutes: int = 60) -> str:
        # В локальном режиме возвращаем "логический" URL,
        # но реальный URL подставим в prepare endpoint (с video_id).
        return "/api/v1/videos/{video_id}/upload/direct"

    def object_exists(self, path: str) -> bool:
        return self.storage.file_exists(path)

    def get_object_metadata(self, path: str) -> dict:
        size = self.storage.get_file_size(path)
        content_type, _ = mimetypes.guess_type(path)
        return {"size": size, "content_type": content_type or "video/mp4"}


# ===================== VIDEO CRUD =====================

@router.post("/", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Создать новое видео (только метаданные)."""
    try:
        video = create_video(db=db, video_data=video_data, user_id=current_user["id"])
        return video
    except Exception as e:
        logger.exception("Error creating video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


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
    db: Session = Depends(get_db),
):
    """Получить список видео с фильтрацией."""
    try:
        filter_data = VideoFilter(
            status=status,
            visibility=visibility,
            owner_id=owner_id,
            min_duration=min_duration,
            max_duration=max_duration,
            search_text=search,
        )
        pagination = VideoPagination(page=page, per_page=per_page)

        # Пока заглушка user_id=1 (как в твоём исходнике)
        videos, total = get_videos(db, filter_data, pagination, user_id=1)

        return {
            "items": [VideoResponse.from_orm(video) for video in videos],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
    except Exception as e:
        logger.exception("Error listing videos")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{video_id}", response_model=VideoResponse)
def get_video_endpoint(video_id: int, db: Session = Depends(get_db)):
    """Получить информацию о видео."""
    try:
        return get_video(db, video_id, user_id=1)  # заглушка
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/{video_id}", response_model=VideoResponse)
def update_video_endpoint(video_id: int, update_data: VideoUpdate, db: Session = Depends(get_db)):
    """Обновить метаданные видео."""
    try:
        return update_video(db, video_id, update_data, user_id=1)  # заглушка
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception("Error updating video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_endpoint(video_id: int, db: Session = Depends(get_db)):
    """Удалить видео."""
    try:
        delete_video(db, video_id, user_id=1)  # заглушка
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception("Error deleting video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ===================== UPLOAD FLOW =====================

@router.post("/upload/prepare", response_model=VideoUploadURL)
def upload_prepare_endpoint(
    payload: VideoUploadCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Подготовить загрузку:
    - создаём Video (status=UPLOADING)
    - генерим storage_path и сохраняем его в video.original_path
    - возвращаем upload_url, куда фронт пошлёт файл
    """
    try:
        storage = get_storage_provider()
        backend = StorageBackendAdapter(storage)

        result = prepare_video_upload(
            db=db,
            upload_data=payload,
            user_id=current_user["id"],
            storage_backend=backend,
        )

        # Для local: реальный URL с video_id
        result.upload_url = f"/api/v1/videos/{result.video_id}/upload/direct"
        return result

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("upload_prepare_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{video_id}/upload/direct")
def upload_direct_endpoint(
    video_id: int,
    file: UploadFile = File(...),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Прямая загрузка файла в локальное хранилище.
    Файл сохраняем по video.original_path (который выставляется в prepare).
    """
    try:
        video = get_video(db, video_id, user_id=current_user["id"])

        if video.owner_id != current_user["id"]:
            raise ForbiddenError("Access denied")

        if not video.original_path:
            raise ValidationError("original_path is empty. Call /upload/prepare first.")

        storage = get_storage_provider()

        try:
            file.file.seek(0)
        except Exception:
            pass

        storage.save_file(file, video.original_path)

        return {"ok": True, "video_id": video_id, "path": video.original_path}

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("upload_direct_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{video_id}/upload/complete", response_model=VideoResponse)
def upload_complete_endpoint(
    video_id: int,
    payload: VideoUploadComplete,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Завершение загрузки:
    - проверяем что файл есть
    - пишем size/mime_type
    - переводим status -> UPLOADED
    - создаём ProcessingTask(METADATA)
    """
    try:
        storage = get_storage_provider()
        backend = StorageBackendAdapter(storage)

        video = complete_video_upload(
            db=db,
            video_id=video_id,
            complete_data=payload,
            user_id=current_user["id"],
            storage_backend=backend,
        )

        set_video_status(video_id, "QUEUED", None)
        publish_video_process(video_id=video_id, path=video.original_path)

        return video

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("upload_complete_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))