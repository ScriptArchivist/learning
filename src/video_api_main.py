# src/video_main.py
from __future__ import annotations

import logging
import logging.config

from fastapi import FastAPI

# logging.ini ожидает request_id/trace_id поля в формате логов.
# В video-api они будут "-", если middleware/record_factory не задан.
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("video-api")

from web.video_api import router as video_api_router  # noqa: E402


def create_app() -> FastAPI:
    app = FastAPI(
        title="video-api",
        version="1.0",
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    app.include_router(video_api_router, prefix="/api/v1")
    return app


app = create_app()