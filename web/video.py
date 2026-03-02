# web/video.py
"""
Эндпоинты для работы с видео: загрузка, просмотр, управление.
"""

import base64
import hashlib
import hmac
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

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
from starlette.responses import FileResponse, HTMLResponse, Response, StreamingResponse

from db.database import get_db_read, get_db_write
from errors import ForbiddenError, NotFoundError, ValidationError
from model.user import UserInDB
from model.video_contract import VideoDetailDTO, VideoListResponse
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
from service.paths import (
    delivery_url as build_delivery_url,
    hls_master as hls_master_key,  # noqa: F401 (может использоваться в других местах)
    hls_dir as hls_dir_key,
)

try:
    from src.config import settings
except ImportError:

    class Settings:
        storage_path = "/app/uploads"
        DELIVERY_MODE = "local"

    settings = Settings()

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/videos", tags=["videos"], redirect_slashes=False)

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")

THUMB_CACHE_CONTROL = "private, max-age=86400"

HLS_CACHE_CONTROL = "private, max-age=60"
HLS_PATH_RE = re.compile(r"^(master\.m3u8|[0-9]{3,4}p/(index\.m3u8|seg_\d{5}\.ts))$")

HLS_TOKEN_SECRET = os.getenv("HLS_TOKEN_SECRET") or "dev-secret-change-me"
if HLS_TOKEN_SECRET == "dev-secret-change-me":
    logger.warning("HLS_TOKEN_SECRET is not set; using weak dev default!")

HLS_TOKEN_TTL_SECONDS = int(os.getenv("HLS_TOKEN_TTL_SECONDS", "300"))
HLS_CLOCK_SKEW_SECONDS = 30


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _sign(msg: str) -> str:
    mac = hmac.new(HLS_TOKEN_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(mac)


def make_hls_token(video_id: int, exp: int, scope: str) -> str:
    msg = f"v={video_id}&exp={exp}&scope={scope}"
    sig = _sign(msg)
    return f"{exp}.{sig}.{scope}"


def verify_hls_token(video_id: int, token: str, expected_scope: str) -> bool:
    try:
        exp_s, sig, scope = token.split(".", 2)
        exp = int(exp_s)
    except Exception:
        return False

    if scope != expected_scope:
        return False

    now = int(time.time())
    if exp < (now - HLS_CLOCK_SKEW_SECONDS):
        return False

    msg = f"v={video_id}&exp={exp}&scope={scope}"
    good = _sign(msg)
    return hmac.compare_digest(sig, good)


def _rewrite_playlist_add_token(playlist_text: str, token: str) -> str:
    out_lines = []
    for line in playlist_text.splitlines():
        if line and not line.startswith("#"):
            joiner = "&" if "?" in line else "?"
            out_lines.append(f"{line}{joiner}token={quote_plus(token)}")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if playlist_text.endswith("\n") else "")


def _full_storage_path(rel_path: str) -> str:
    base = getattr(settings, "storage_path", "/app/uploads") or "/app/uploads"
    return str(Path(base) / rel_path.lstrip("/"))


def _delivery_url(object_key: str) -> str:
    return build_delivery_url(object_key)


class StorageBackendAdapter:
    def __init__(self, storage):
        self.storage = storage

    def generate_presigned_upload_url(self, object_name: str, file_size: int, expires_minutes: int = 60) -> str:
        # В local режиме мы всегда грузим напрямую в API (upload_direct_endpoint)
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


def _range_stream_response(file_path: str, content_type: str, request: Request):
    path = Path(file_path)
    file_size = path.stat().st_size

    headers = {"Accept-Ranges": "bytes", "Content-Type": content_type}
    range_header = request.headers.get("range")

    if not range_header:
        headers["Content-Length"] = str(file_size)
        return FileResponse(str(path), media_type=content_type, headers=headers)

    m = RANGE_RE.match(range_header)
    if not m:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start_s, end_s = m.groups()
    if start_s == "" and end_s == "":
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    if start_s == "":
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

    headers.update({"Content-Range": f"bytes {start}-{end}/{file_size}", "Content-Length": str(chunk_size)})

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            buf = 1024 * 1024
            while remaining > 0:
                read_size = min(buf, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(iterfile(), status_code=206, headers=headers, media_type=content_type)


# -------------------- CRUD --------------------


@router.post("", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    return create_video(db=db, video_data=video_data, user_id=current_user["id"])


@router.get("", response_model=VideoListResponse)
@router.get("/", response_model=VideoListResponse)
def list_videos(
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
    return VideoListResponse(items=[to_list_item(v) for v in videos], total=total, page=page, per_page=per_page)


@router.get("/{video_id}", response_model=VideoDetailDTO)
def get_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    video = get_video(db, video_id, user_id=current_user["id"])
    return to_detail(video)


@router.put("/{video_id}", response_model=VideoResponse)
def update_video_endpoint(
    video_id: int,
    update_data: VideoUpdate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    incoming = update_data.dict(exclude_unset=True)
    allowed_fields = {"title", "description", "visibility"}
    forbidden = set(incoming.keys()) - allowed_fields
    if forbidden:
        raise HTTPException(status_code=422, detail=f"Forbidden fields in update: {sorted(forbidden)}")
    return VideoResponse.from_orm(update_video(db, video_id, update_data, user_id=current_user["id"]))


@router.delete("/{video_id}", status_code=status.HTTP_200_OK)
def delete_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    delete_video(db, video_id, user_id=current_user["id"])
    return {"status": "deleted", "video_id": video_id}


# -------------------- FILE / STREAM --------------------


@router.api_route("/{video_id}/file", methods=["GET", "HEAD"])
def get_video_file_endpoint(
    video_id: int,
    request: Request,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video(db, video_id, user_id=current_user["id"])
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")
    if not video.original_path:
        raise HTTPException(status_code=404, detail="Video file path is empty")

    full_path = _full_storage_path(video.original_path)
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    content_type = video.mime_type or mimetypes.guess_type(full_path)[0] or "video/mp4"
    return _range_stream_response(full_path, content_type, request)


# -------------------- WATCH (HTML) --------------------


@router.api_route("/{video_id}/watch", methods=["GET", "HEAD"], response_class=HTMLResponse)
def watch_video_page(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        if video.status != VideoStatus.READY:
            raise HTTPException(status_code=409, detail="Video is not ready")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return HTMLResponse(
        f"""<!doctype html>
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

    <video id="player" controls preload="metadata"
      poster="/api/v1/videos/{video_id}/thumbnail"
      src="/api/v1/videos/{video_id}/file">
    </video>

    <div class="row">
      <a href="/api/v1/videos/{video_id}">JSON</a>
      <a href="/api/v1/videos/{video_id}/file">MP4</a>
      <a href="/api/v1/videos/{video_id}/hls/master.m3u8">HLS</a>
      <a href="/api/v1/videos/{video_id}/thumbnail">Thumbnail</a>
    </div>

    <div class="muted">
      HLS раздаётся через API с проверкой прав. Если HLS недоступен/не готов — останемся на MP4.
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
  (async function() {{
    const video = document.getElementById("player");
    const mode = document.getElementById("mode");

    const hlsUrl = "/api/v1/videos/{video_id}/hls/master.m3u8";
    const mp4Url = "/api/v1/videos/{video_id}/file";

    function setMode(t) {{
      mode.textContent = t;
      console.log("[watch]", t);
    }}

    try {{
      const resp = await fetch(hlsUrl, {{ method: "GET" }});
      if (!resp.ok) throw new Error("HLS playlist HTTP " + resp.status);

      if (!window.Hls) {{
        setMode("MP4 (hls.js not loaded)");
        return;
      }}

      if (Hls.isSupported()) {{
        setMode("HLS (hls.js)");
        try {{
          video.pause();
          video.removeAttribute("src");
          video.load();
        }} catch (e) {{}}

        const hls = new Hls({{ debug: true }});
        hls.on(Hls.Events.ERROR, function (event, data) {{
          console.error("[hls.js error]", data);
          if (data && data.fatal) {{
            setMode("MP4 (HLS fatal)");
            try {{ hls.destroy(); }} catch (e) {{}}
            video.src = mp4Url;
            video.load();
          }}
        }});

        hls.loadSource(hlsUrl);
        hls.attachMedia(video);
        return;
      }}

      if (video.canPlayType("application/vnd.apple.mpegurl")) {{
        setMode("HLS (native)");
        video.src = hlsUrl;
        video.load();
        return;
      }}

      setMode("MP4 (no HLS support)");
    }} catch (e) {{
      console.error("[watch init error]", e);
      setMode("MP4 (HLS not ready)");
    }}
  }})();
  </script>
</body>
</html>"""
    )


@router.api_route("/shared/{token}/watch", methods=["GET", "HEAD"], response_class=HTMLResponse)
def watch_shared_video_page(
    token: str,
    db: Session = Depends(get_db_read),
):
    try:
        video = get_video_by_share_token(db, token)
        if video.status != VideoStatus.READY:
            raise HTTPException(status_code=409, detail="Video is not ready")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return HTMLResponse(
        f"""<!doctype html>
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
      <a href="/api/v1/videos/shared/{token}/hls/master.m3u8">HLS</a>
      <a href="/api/v1/videos/shared/{token}/thumbnail">Thumbnail</a>
    </div>

    <div class="muted">
      Unlisted-доступ по токену. HLS раздаётся через API по token; если HLS не готов — включится MP4.
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
  (async function() {{
    const video = document.getElementById("player");
    const mode = document.getElementById("mode");

    const hlsUrl = "/api/v1/videos/shared/{token}/hls/master.m3u8";
    const mp4Url = "/api/v1/videos/shared/{token}/file";

    function setMode(t) {{
      mode.textContent = t;
      console.log("[watch-shared]", t);
    }}

    async function useMp4(reason) {{
      setMode("MP4" + (reason ? (" (" + reason + ")") : ""));
      video.src = mp4Url;
      video.load();
    }}

    try {{
      const resp = await fetch(hlsUrl, {{ method: "GET" }});
      if (!resp.ok) throw new Error("HLS playlist HTTP " + resp.status);

      if (window.Hls && Hls.isSupported()) {{
        setMode("HLS (hls.js)");
        try {{
          video.pause();
          video.removeAttribute("src");
          video.load();
        }} catch (e) {{}}

        const hls = new Hls({{ debug: true }});
        hls.on(Hls.Events.ERROR, function (event, data) {{
          console.error("[hls.js error]", data);
          if (data && data.fatal) {{
            try {{ hls.destroy(); }} catch (e) {{}}
            useMp4("HLS fatal");
          }}
        }});

        hls.loadSource(hlsUrl);
        hls.attachMedia(video);
        return;
      }}

      if (video.canPlayType("application/vnd.apple.mpegurl")) {{
        setMode("HLS (native)");
        video.src = hlsUrl;
        video.load();
        return;
      }}

      await useMp4("no HLS support");
    }} catch (e) {{
      await useMp4("HLS not ready");
    }}
  }})();
  </script>
</body>
</html>"""
    )


# -------------------- UPLOAD FLOW --------------------


@router.post("/upload/prepare", response_model=VideoUploadURL)
def upload_prepare_endpoint(
    payload: VideoUploadCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    storage = get_storage_provider()
    backend = StorageBackendAdapter(storage)
    try:
        result = prepare_video_upload(db=db, upload_data=payload, user_id=current_user["id"], storage_backend=backend)
        result.upload_url = f"/api/v1/videos/{result.video_id}/upload/direct"
        return result
    except (ValidationError, NotFoundError, ForbiddenError, VideoStatusTransitionError) as e:
        db.rollback()
        code = 400
        if isinstance(e, NotFoundError):
            code = 404
        if isinstance(e, ForbiddenError):
            code = 403
        if isinstance(e, VideoStatusTransitionError):
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
    if video.status != VideoStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="Upload is not allowed in this status")
    if video.owner_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    if not video.original_path:
        raise HTTPException(status_code=400, detail="original_path is empty. Call /upload/prepare first.")

    storage = get_storage_provider()
    try:
        file.file.seek(0)
    except Exception:
        pass

    storage.save_file(file, video.original_path)
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
    except (NotFoundError, ForbiddenError, ValidationError, VideoStatusTransitionError) as e:
        db.rollback()
        code = 400
        if isinstance(e, NotFoundError):
            code = 404
        if isinstance(e, ForbiddenError):
            code = 403
        if isinstance(e, VideoStatusTransitionError):
            code = 409
        raise HTTPException(status_code=code, detail=str(e))


# -------------------- THUMBNAIL --------------------


@router.api_route("/{video_id}/thumbnail", methods=["GET", "HEAD"])
def get_video_thumbnail_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video(db, video_id, user_id=current_user["id"])
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")
    if not video.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not ready")

    full_path = _full_storage_path(video.thumbnail_path)
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return FileResponse(full_path, media_type="image/jpeg", headers={"Cache-Control": THUMB_CACHE_CONTROL})


@router.api_route("/shared/{token}/thumbnail", methods=["GET", "HEAD"])
def get_shared_video_thumbnail_endpoint(
    token: str,
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video_by_share_token(db, token)
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")
    if not video.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not ready")

    full_path = _full_storage_path(video.thumbnail_path)
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return FileResponse(full_path, media_type="image/jpeg", headers={"Cache-Control": THUMB_CACHE_CONTROL})


# -------------------- SHARE --------------------


@router.post("/{video_id}/share", response_model=ShareLinkResponse)
def create_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    token = create_share_link(db, video_id=video_id, user_id=current_user["id"])
    return ShareLinkResponse(video_id=video_id, share_url=f"/api/v1/videos/shared/{token}")


@router.post("/{video_id}/share/revoke", response_model=RevokeShareResponse)
def revoke_share_link_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    revoke_share_link(db, video_id=video_id, user_id=current_user["id"])
    return RevokeShareResponse(video_id=video_id, revoked=True)


@router.get("/shared/{token}", response_model=VideoDetailDTO)
def get_shared_video_endpoint(
    token: str,
    db: Session = Depends(get_db_read),
):
    video = get_video_by_share_token(db, token)
    return to_detail(video, shared_token=token)


# ✅ ВАЖНО: shared file ДОЛЖЕН быть именно на /shared/{token}/file
@router.api_route("/shared/{token}/file", methods=["GET", "HEAD"])
def get_shared_video_file_endpoint(
    token: str,
    request: Request,
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video_by_share_token(db, token)
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")
    if not video.original_path:
        raise HTTPException(status_code=404, detail="Video file path is empty")

    full_path = _full_storage_path(video.original_path)
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    content_type = video.mime_type or mimetypes.guess_type(full_path)[0] or "video/mp4"
    return _range_stream_response(full_path, content_type, request)


# -------------------- HLS (AUTH + SHARED) --------------------


@router.api_route("/{video_id}/hls/{hls_path:path}", methods=["GET", "HEAD"])
def get_video_hls_file(
    video_id: int,
    hls_path: str,
    request: Request,
    token: str = Query(None, description="HLS TTL token (required for .ts)"),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video(db, video_id, user_id=current_user["id"])
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")

    if not HLS_PATH_RE.match(hls_path):
        raise HTTPException(status_code=400, detail="Invalid HLS path")

    full_path = _full_storage_path(f"{hls_dir_key(video_id)}/{hls_path}")
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="HLS file not ready")

    exp = int(time.time()) + HLS_TOKEN_TTL_SECONDS
    issued_token = make_hls_token(video_id=video_id, exp=exp, scope="auth")

    # плейлисты отдаём без проверки входящего токена, но вписываем свежий токен в ссылки
    if full_path.endswith(".m3u8"):
        content = Path(full_path).read_text(encoding="utf-8")
        content = _rewrite_playlist_add_token(content, issued_token)
        return Response(
            content=content,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": HLS_CACHE_CONTROL},
        )

    # сегменты защищаем токеном
    if not token or not verify_hls_token(video_id, token, expected_scope="auth"):
        raise HTTPException(status_code=403, detail="Invalid/expired HLS token")

    # важно: сегменты тоже поддерживают Range
    return _range_stream_response(full_path, "video/mp2t", request)


@router.api_route("/shared/{token}/hls/{hls_path:path}", methods=["GET", "HEAD"])
def get_shared_hls_file(
    token: str,
    hls_path: str,
    request: Request,
    hls_token: str = Query(None, alias="token", description="HLS TTL token"),
    db: Session = Depends(get_db_read),
):
    if getattr(settings, "DELIVERY_MODE", "local") == "url":
        raise HTTPException(status_code=501, detail="Delivery is handled by origin")

    video = get_video_by_share_token(db, token)
    if video.status != VideoStatus.READY:
        raise HTTPException(status_code=409, detail="Video is not ready")

    if not HLS_PATH_RE.match(hls_path):
        raise HTTPException(status_code=400, detail="Invalid HLS path")

    full_path = _full_storage_path(f"{hls_dir_key(video.id)}/{hls_path}")
    if not Path(full_path).exists():
        raise HTTPException(status_code=404, detail="HLS file not ready")

    scope = f"share:{token}"
    exp = int(time.time()) + HLS_TOKEN_TTL_SECONDS
    issued_token = make_hls_token(video_id=video.id, exp=exp, scope=scope)

    if full_path.endswith(".m3u8"):
        content = Path(full_path).read_text(encoding="utf-8")
        content = _rewrite_playlist_add_token(content, issued_token)
        return Response(
            content=content,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": HLS_CACHE_CONTROL},
        )

    if not hls_token or not verify_hls_token(video.id, hls_token, expected_scope=scope):
        raise HTTPException(status_code=403, detail="Invalid/expired HLS token")

    # важно: shared сегменты тоже поддерживают Range
    return _range_stream_response(full_path, "video/mp2t", request)