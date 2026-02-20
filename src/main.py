# src/main.py

import logging
import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- LogRecordFactory: гарантируем request_id/trace_id для всех логов (включая uvicorn) ---
from service.correlation import get_request_id, get_trace_id, set_request_id, set_trace_id

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
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        tid = request.headers.get("X-Trace-Id")  # опционально

        set_request_id(rid)
        set_trace_id(tid)

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        if tid:
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

from web.video import router as video_router

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
async def health_check():
    return {
        "status": "healthy",
        "service": "Video Platform API",
        "database": "connected",  # TODO: добавить реальную проверку БД
    }