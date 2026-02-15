# src/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import mimetypes

app = FastAPI()

# ===================== HLS CONFIG =====================

# MIME-типы для HLS (в slim образах часто не хватает)
mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")
mimetypes.add_type("video/mp2t", ".ts")

# ⚠️ ВАЖНО: создать директорию ДО mount,
# иначе StaticFiles упадёт если папки нет
Path("/app/uploads/hls").mkdir(parents=True, exist_ok=True)

# Раздаём HLS из общего volume uploads_data
#app.mount("/hls", StaticFiles(directory="/app/uploads/hls"), name="hls")

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
