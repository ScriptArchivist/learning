# src/live_api_main.py
from __future__ import annotations

import logging

from fastapi import FastAPI

from service.logging_filter import CorrelationFilter
from web.live import router as live_router


def create_app() -> FastAPI:
    # Чтобы форматтер из logging.ini (request_id/trace_id) не падал
    logging.getLogger().addFilter(CorrelationFilter())

    app = FastAPI(title="live-api", version="1.0")
    app.include_router(live_router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()