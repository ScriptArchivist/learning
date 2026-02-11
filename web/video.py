# web/video.py
"""
Эндпоинты для работы с видео: загрузка, просмотр, управление.
"""

# stdlib
import logging
import mimetypes
import os
import re
from pathlib import Path
from typing import Optional

# third-party
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session
from starlette.responses import FileResponse, Response, StreamingResponse

# local
from db.database import get_db
from errors import ForbiddenError, NotFoundError, ValidationError
from model.user import UserInDB
from model.video import (
    RevokeShareResponse,
    ShareLinkResponse,
    VideoCreate,
    VideoFilter,
    VideoPagination,
    VideoResponse,
    VideoStatus,
    VideoUpdate,
    VideoUploadComplete,
    VideoUploadCreate,
    VideoUploadURL,
    Visibility,
)
from service.broker import publish_video_process
from service.security import get_current_user as get_current_user_stub
from service.storage_service import get_storage_provider
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
from starlette.responses import HTMLResponse


# настройки (чтобы знать корень хранилища)
try:
    from src.config import settings
except ImportError:

    class Settings:
        storage_path = "/app/uploads"

    settings = Settings()

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


def _full_storage_path(rel_path: str) -> str:
    """
    rel_path вида: original/1/1/xxx.mp4
    settings.storage_path у тебя должен быть /app/uploads (в docker)
    """
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return str(Path(base) / rel_path)

def _hls_playlist_path(video_id: int) -> str:
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return str(Path(base) / "hls" / str(video_id) / "index.m3u8")

def _hls_playlist_url(video_id: int) -> str:
    return f"/hls/{video_id}/index.m3u8"



# ===================== RANGE STREAMING HELPERS =====================

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _range_stream_response(file_path: str, content_type: str, request: Request):
    """
    Возвращает видео-файл с поддержкой HTTP Range (206 Partial Content),
    чтобы HTML5 <video> мог нормально стартовать и перематывать.
    """
    path = Path(file_path)
    file_size = path.stat().st_size

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type,
    }

    range_header = request.headers.get("range")

    # Если Range не запросили — можно отдать целиком (200 OK)
    if not range_header:
        headers["Content-Length"] = str(file_size)
        return FileResponse(str(path), media_type=content_type, headers=headers)

    m = RANGE_RE.match(range_header)
    if not m:
        # Некорректный Range
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start_s, end_s = m.groups()
    if start_s == "" and end_s == "":
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    if start_s == "":
        # bytes=-N (последние N байт)
        length = int(end_s)
        start = max(file_size - length, 0)
        end = file_size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else file_size - 1

    if start >= file_size or end < start:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    end = min(end, file_size - 1)
    chunk_size = end - start + 1

    headers.update(
        {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_size),
        }
    )

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            buf = 1024 * 1024  # 1MB
            while remaining > 0:
                read_size = min(buf, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(iterfile(), status_code=206, headers=headers, media_type=content_type)


# ===================== VIDEO CRUD =====================

@router.post("/", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Создать новое видео (только метаданные)."""
    try:
        return create_video(db=db, video_data=video_data, user_id=current_user["id"])
    except Exception as e:
        logger.exception("Error creating video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=dict)
def list_videos(
    status: Optional[VideoStatus] = Query(None, description="Фильтр по статусу"),
    visibility: Optional[Visibility] = Query(None, description="Фильтр по видимости"),
    owner_id: Optional[int] = Query(None, description="Фильтр по владельцу"),
    min_duration: Optional[float] = Query(None, description="Минимальная длительность"),
    max_duration: Optional[float] = Query(None, description="Максимальная длительность"),
    search: Optional[str] = Query(None, description="Поиск по названию и описанию"),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Количество на странице"),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Получить список видео:
    - PUBLIC видят все
    - свои видео видит владелец (включая PRIVATE/UNLISTED)
    - сортировка по uploaded_at DESC уже в service.get_videos
    """
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

        videos, total = get_videos(db, filter_data, pagination, user_id=current_user["id"])

        items = []
        for v in videos:
            r = VideoResponse.from_orm(v)
            hls_path = _hls_playlist_path(v.id)
            r.hls_ready = Path(hls_path).exists()
            r.hls_url = _hls_playlist_url(v.id) if r.hls_ready else None
            items.append(r)

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
    except Exception as e:
        logger.exception("Error listing videos")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{video_id}", response_model=VideoResponse)
def get_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Получить информацию о видео (с проверкой доступа)."""
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        resp = VideoResponse.from_orm(video)
        hls_path = _hls_playlist_path(video_id)
        resp.hls_ready = Path(hls_path).exists()
        resp.hls_url = _hls_playlist_url(video_id) if resp.hls_ready else None
        return resp
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/{video_id}", response_model=VideoResponse)
def update_video_endpoint(
    video_id: int,
    update_data: VideoUpdate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Обновить метаданные видео (только владелец)."""
    try:
        return VideoResponse.from_orm(update_video(db, video_id, update_data, user_id=current_user["id"]))
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception("Error updating video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Удалить видео (только владелец)."""
    try:
        delete_video(db, video_id, user_id=current_user["id"])
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception("Error deleting video")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ===================== FILE/STREAM =====================

@router.api_route("/{video_id}/file", methods=["GET", "HEAD"])
@router.get("/{video_id}/file")
def get_video_file_endpoint(
    video_id: int,
    request: Request,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Отдаём оригинальный файл видео с поддержкой Range.
    """
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        if not video.original_path:
            raise HTTPException(status_code=404, detail="Video file path is empty")

        full_path = _full_storage_path(video.original_path)
        if not Path(full_path).exists():
            raise HTTPException(status_code=404, detail="Video file not found on disk")

        content_type = video.mime_type or mimetypes.guess_type(full_path)[0] or "video/mp4"
        return _range_stream_response(full_path, content_type, request)

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ===================== SHARE LINKS (UNLISTED) =====================

@router.post("/{video_id}/share", response_model=ShareLinkResponse)
def create_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """
    Делает видео UNLISTED и создаёт share_token.
    Возвращает ссылку, по которой можно смотреть без логина.
    """
    try:
        token = create_share_link(db, video_id=video_id, user_id=current_user["id"])
        return ShareLinkResponse(video_id=video_id, share_url=f"/api/v1/videos/shared/{token}")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{video_id}/share/revoke", response_model=RevokeShareResponse)
def revoke_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    """Отключить доступ по ссылке."""
    try:
        revoke_share_link(db, video_id=video_id, user_id=current_user["id"])
        return RevokeShareResponse(video_id=video_id, revoked=True)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/shared/{token}", response_model=VideoResponse)
def get_shared_video_endpoint(token: str, db: Session = Depends(get_db)):
    """Получить метаданные UNLISTED видео по ссылке (без логина)."""
    try:
        video = get_video_by_share_token(db, token)

        resp = VideoResponse.from_orm(video)
        hls_path = _hls_playlist_path(video.id)
        resp.hls_ready = Path(hls_path).exists()
        resp.hls_url = _hls_playlist_url(video.id) if resp.hls_ready else None
        return resp

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/shared/{token}/file")
def get_shared_video_file_endpoint(token: str, request: Request, db: Session = Depends(get_db)):
    """Получить файл UNLISTED видео по ссылке (без логина) с поддержкой Range."""
    try:
        video = get_video_by_share_token(db, token)
        if not video.original_path:
            raise HTTPException(status_code=404, detail="Video file path is empty")

        full_path = _full_storage_path(video.original_path)
        if not Path(full_path).exists():
            raise HTTPException(status_code=404, detail="Video file not found on disk")

        content_type = video.mime_type or mimetypes.guess_type(full_path)[0] or "video/mp4"
        return _range_stream_response(full_path, content_type, request)

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


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
    - публикуем задачу в Rabbit (worker обработает)
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

        publish_video_process(video_id=video_id, path=video.original_path)

        return VideoResponse.from_orm(video)

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("upload_complete_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


# ===================== FILE/STREAM =====================

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
THUMB_CACHE_CONTROL = "private, max-age=86400"


@router.api_route("/{video_id}/thumbnail", methods=["GET", "HEAD"])
def get_video_thumbnail_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        if not video.thumbnail_path:
            raise HTTPException(status_code=404, detail="Thumbnail not ready")

        full_path = _full_storage_path(video.thumbnail_path)
        if not Path(full_path).exists():
            raise HTTPException(status_code=404, detail="Thumbnail file not found")

        return FileResponse(
            full_path,
            media_type="image/jpeg",
            headers={"Cache-Control": THUMB_CACHE_CONTROL},
        )

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.api_route("/shared/{token}/thumbnail", methods=["GET", "HEAD"])
def get_shared_video_thumbnail_endpoint(token: str, db: Session = Depends(get_db)):
    """Получить thumbnail UNLISTED видео по ссылке (без логина)."""
    try:
        video = get_video_by_share_token(db, token)
        if not video.thumbnail_path:
            raise HTTPException(status_code=404, detail="Thumbnail not ready")

        full_path = _full_storage_path(video.thumbnail_path)
        if not Path(full_path).exists():
            raise HTTPException(status_code=404, detail="Thumbnail file not found")

        return FileResponse(
            full_path,
            media_type="image/jpeg",
            headers={"Cache-Control": THUMB_CACHE_CONTROL},
        )

    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{video_id}/watch", response_class=HTMLResponse)
def watch_video_page(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db),
):
    # проверяем, что видео существует и доступно пользователю
    _ = get_video(db, video_id, user_id=current_user["id"])

    return HTMLResponse(f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video {video_id}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }}
    .wrap {{ max-width: 980px; margin: 0 auto; }}
    video {{ width: 100%; background:#000; border-radius: 12px; }}
    .row {{ display:flex; gap: 12px; flex-wrap:wrap; margin-top: 12px; }}
    a {{ color:#0b66ff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .muted {{ color:#666; font-size:14px; margin-top: 10px; }}
    .badge {{ display:inline-block; padding: 3px 8px; border-radius: 999px; background:#f2f2f2; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Видео #{video_id}</h1>

    <div class="muted">
      <span class="badge" id="mode">MP4 (default)</span>
    </div>

    <!-- MP4 по умолчанию: работает всегда -->
    <video id="player" controls preload="metadata"
      poster="/api/v1/videos/{video_id}/thumbnail"
      src="/api/v1/videos/{video_id}/file">
    </video>

    <div class="row">
      <a href="/api/v1/videos/{video_id}">JSON</a>
      <a href="/api/v1/videos/{video_id}/file">MP4</a>
      <a href="/hls/{video_id}/index.m3u8">HLS</a>
      <a href="/api/v1/videos/{video_id}/thumbnail">Thumbnail</a>
    </div>

    <div class="muted">
      Если hls.js доступен и плейлист существует — переключимся на HLS. Иначе останемся на MP4.
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
  (async function() {{
    const video = document.getElementById("player");
    const mode = document.getElementById("mode");

    const hlsUrl = "/hls/{video_id}/index.m3u8";
    const mp4Url = "/api/v1/videos/{video_id}/file";

    function setMode(t) {{
      mode.textContent = t;
      console.log("[watch]", t);
    }}

    try {{
      // Проверим, что плейлист реально есть
      const resp = await fetch(hlsUrl, {{ method: "GET" }});
      if (!resp.ok) throw new Error("HLS playlist HTTP " + resp.status);

      // Если hls.js не загрузился — остаёмся на MP4
      if (!window.Hls) {{
        setMode("MP4 (hls.js not loaded)");
        return;
      }}

      // Chrome/Firefox/Edge: через hls.js
      if (Hls.isSupported()) {{
        setMode("HLS (hls.js)");

        // ✅ КЛЮЧЕВОЙ ФИКС:
        // перед переключением на HLS очищаем mp4 src,
        // иначе hls.js иногда не может нормально перехватить video element
        try {{
          video.pause();
          video.removeAttribute("src");
          video.load();
        }} catch (e) {{
          console.warn("[watch] failed to reset video src", e);
        }}

        const hls = new Hls({{ debug: true }});

        hls.on(Hls.Events.ERROR, function (event, data) {{
          console.error("[hls.js error]", data);
          if (data && data.fatal) {{
            // фатально — возвращаем MP4
            setMode("MP4 (HLS fatal: " + data.type + "/" + data.details + ")");
            try {{
              hls.destroy();
            }} catch (e) {{}}
            video.src = mp4Url;
            video.load();
          }}
        }});

        hls.loadSource(hlsUrl);
        hls.attachMedia(video);
        return;
      }}

      // Safari: нативный HLS
      if (video.canPlayType("application/vnd.apple.mpegurl")) {{
        setMode("HLS (native)");
        video.src = hlsUrl;
        video.load();
        return;
      }}

      setMode("MP4 (no HLS support)");
    }} catch (e) {{
      console.error("[watch init error]", e);
      setMode("MP4 (HLS not ready: " + (e.message || "error") + ")");
    }}
  }})();
  </script>
</body>
</html>""")


@router.get("/shared/{token}/watch", response_class=HTMLResponse)
def watch_shared_video_page(token: str, db: Session = Depends(get_db)):
    video = get_video_by_share_token(db, token)

    return HTMLResponse(f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Shared video</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }}
    .wrap {{ max-width: 980px; margin: 0 auto; }}
    video {{ width: 100%; background:#000; border-radius: 12px; }}
    .row {{ display:flex; gap: 12px; flex-wrap:wrap; margin-top: 12px; }}
    a {{ color:#0b66ff; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .muted {{ color:#666; font-size:14px; margin-top: 10px; }}
    .badge {{ display:inline-block; padding: 3px 8px; border-radius: 999px; background:#f2f2f2; font-size: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Видео по ссылке</h1>

    <div class="muted">
      <span class="badge" id="mode">loading…</span>
    </div>

    <video id="player" controls preload="metadata"
      poster="/api/v1/videos/shared/{token}/thumbnail">
    </video>

    <div class="row">
      <a href="/api/v1/videos/shared/{token}">JSON</a>
      <a href="/api/v1/videos/shared/{token}/file">MP4</a>
      <a href="/hls/{video.id}/index.m3u8">HLS</a>
      <a href="/api/v1/videos/shared/{token}/thumbnail">Thumbnail</a>
    </div>

    <div class="muted">
      Unlisted-доступ по токену. Если HLS ещё не готов — включится MP4 (Range 206).
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
  (async function() {{
    const video = document.getElementById("player");
    const mode = document.getElementById("mode");

    const hlsUrl = "/hls/{video.id}/index.m3u8";
    const mp4Url = "/api/v1/videos/shared/{token}/file";

    async function useMp4() {{
      mode.textContent = "MP4";
      video.src = mp4Url;
    }}

    try {{
      // Проверяем, что плейлист реально существует
      const resp = await fetch(hlsUrl, {{ method: "GET" }});
      if (!resp.ok) throw new Error("HLS not ready");

      // Chrome/Firefox/Edge: через hls.js
      if (window.Hls && Hls.isSupported()) {{
        mode.textContent = "HLS (hls.js)";
        const hls = new Hls();
        hls.loadSource(hlsUrl);
        hls.attachMedia(video);
        return;
      }}

      // Safari: HLS нативно
      if (video.canPlayType("application/vnd.apple.mpegurl")) {{
        mode.textContent = "HLS (native)";
        video.src = hlsUrl;
        return;
      }}

      await useMp4();
    }} catch (e) {{
      await useMp4();
    }}
  }})();
  </script>
</body>
</html>""")