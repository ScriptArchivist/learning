# src/video_main.py
from __future__ import annotations

import logging
import logging.config
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ВАЖНО: logging.ini может требовать request_id/trace_id, а uvicorn пишет логи до твоих record_factory.
# Поэтому тут НЕ пытаемся усложнять — просто грузим конфиг, а если его нет — стандартный logging.
try:
    logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
except Exception:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

logger = logging.getLogger("video-api")


def create_app() -> FastAPI:
    app = FastAPI(
        title="video-api",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # health для docker/k8s
    @app.get("/health")
    def health():
        return {"ok": True, "service": "video-api"}

    # CORS (как минимум для локальной разработки Flutter/Web)
    allow_origins = os.getenv("CORS_ALLOW_ORIGINS", "")
    allow_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "")
    if allow_origins or allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in allow_origins.split(",") if o.strip()] or ["*"],
            allow_origin_regex=allow_origin_regex or None,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # API v1
    from web.video_api import router as video_router  # файл у тебя есть: web/video_api.py

    app.include_router(video_router, prefix="/api/v1")

    return app


app = create_app()
logger.info("boot: video-api app created")