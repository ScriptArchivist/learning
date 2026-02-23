# src/main.py

import logging
import mimetypes
import uuid
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # noqa: F401  (может быть нужен позже)

from sqlalchemy import text

from db.database import SessionLocal
from service.correlation import get_request_id, get_trace_id, set_request_id, set_trace_id
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая uvicorn) ---
_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    record.request_id = get_request_id() or "-"
    record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)
# ----------------------------------------------------------------------------------------

app = FastAPI()

# ===================== REQUEST CORRELATION =====================


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # correlation_id/request_id
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # trace_id: если клиент не прислал — генерим сами
        tid = request.headers.get("X-Trace-Id") or str(uuid.uuid4())

        set_request_id(rid)
        set_trace_id(tid)

        response: StarletteResponse = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Trace-Id"] = tid
        return response


app.add_middleware(RequestIdMiddleware)

# ===================== HLS CONFIG =====================

# MIME-типы для HLS (в slim образах часто не хватает)
mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")
mimetypes.add_type("video/mp2t", ".ts")

# ⚠️ ВАЖНО: создать директорию ДО mount,
# иначе StaticFiles упадёт если папки нет
Path("/app/uploads/hls").mkdir(parents=True, exist_ok=True)

# Раздаём HLS из общего volume uploads_data
# app.mount("/hls", StaticFiles(directory="/app/uploads/hls"), name="hls")

# ===================== CORS =====================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В разработке. В продакшене укажи конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===================== ROUTERS =====================

from web.video import router as video_router  # noqa: E402

app.include_router(video_router, prefix="/api/v1")

# ===================== ROOT =====================


@app.get("/")
async def root():
    return {
        "service": "Video Platform API",
        "version": "1.0",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "videos": "/api/v1/videos",
            "upload": "/api/v1/videos/upload/prepare",
        },
    }


@app.get("/health")
async def health_check(response: Response):
    """
    Healthcheck НЕ "всегда connected", а реально пингует БД.
    Если БД недоступна — возвращает HTTP 503.
    """
    try:
        db = SessionLocal()
        try:
            db.execute(text("select 1"))
        finally:
            db.close()

        return {
            "status": "healthy",
            "service": "Video Platform API",
            "database": "connected",
        }

    except Exception as e:
        response.status_code = 503
        return {
            "status": "unhealthy",
            "service": "Video Platform API",
            "database": "down",
            "error": f"{type(e).__name__}: {str(e)}",
        }