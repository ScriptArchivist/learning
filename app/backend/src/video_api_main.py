# src/video_api_main.py
from __future__ import annotations

import logging
import logging.config
import os

from fastapi import FastAPI
from sqlalchemy import create_engine, text

from db.models import Video
from src.metrics import (
    install_http_metrics,
    set_replica_row_count,
    set_replica_row_diff,
)


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


def build_replica_metrics_refresh():
    write_url = os.getenv("database_write_url")
    read_url = os.getenv("database_read_url")

    if not write_url or not read_url:
        return None

    table_name = getattr(Video, "__tablename__", "videos")
    stmt = text(f"select count(*) from {table_name}")

    write_engine = create_engine(write_url, pool_pre_ping=True)
    read_engine = create_engine(read_url, pool_pre_ping=True)
    same_target = write_url == read_url

    def refresh() -> None:
        with write_engine.connect() as conn:
            master_count = int(conn.execute(stmt).scalar() or 0)

        if same_target:
            replica_count = master_count
        else:
            with read_engine.connect() as conn:
                replica_count = int(conn.execute(stmt).scalar() or 0)

        set_replica_row_count("video-api", "master", "videos", master_count)
        set_replica_row_count("video-api", "replica", "videos", replica_count)
        set_replica_row_diff("video-api", "videos", abs(master_count - replica_count))

    return refresh


install_log_record_defaults()
logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("video-api")

from web.video_api import router as video_api_router  # noqa: E402


def create_app() -> FastAPI:
    app = FastAPI(
        title="video-api",
        version="1.0",
    )

    install_http_metrics(app, "video-api", refresh_callback=build_replica_metrics_refresh())

    @app.get("/health")
    def health():
        return {"ok": True}

    app.include_router(video_api_router, prefix="/api/v1")
    return app


app = create_app()