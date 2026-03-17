# src/live_api_main.py
from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy import func

from db.database import SessionLocalWrite
from db.models import LiveSession
from service.correlation import get_request_id, get_trace_id
from service.logging_filter import CorrelationFilter
from src.metrics import install_http_metrics, set_live_active_sessions
from web.live import router as live_router


_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    if not hasattr(record, "request_id"):
        record.request_id = get_request_id() or "-"
    if not hasattr(record, "trace_id"):
        record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)


def _refresh_live_metrics() -> None:
    db = SessionLocalWrite()
    try:
        active_count = (
            db.query(func.count(LiveSession.id))
            .filter(LiveSession.status.in_(("created", "started")))
            .scalar()
            or 0
        )
        set_live_active_sessions("live-api", int(active_count))
    finally:
        db.close()


def create_app() -> FastAPI:
    logging.getLogger().addFilter(CorrelationFilter())

    app = FastAPI(title="live-api", version="1.0")
    install_http_metrics(app, "live-api", refresh_callback=_refresh_live_metrics)

    app.include_router(live_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()