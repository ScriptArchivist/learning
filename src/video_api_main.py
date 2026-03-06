# src/video_api_main.py
from __future__ import annotations

import logging
import logging.config

from fastapi import FastAPI


def install_log_record_defaults() -> None:
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)

        if not hasattr(record, "request_id"):
            record.request_id = "-"

        if not hasattr(record, "trace_id"):
            record.trace_id = "-"

        return record

    logging.setLogRecordFactory(record_factory)


install_log_record_defaults()
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