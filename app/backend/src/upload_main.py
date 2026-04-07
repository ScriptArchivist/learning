# src/upload_main.py
import logging
import logging.config
import uuid

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

from service.correlation import get_request_id, get_trace_id, set_request_id, set_trace_id
from src.metrics import install_http_metrics

_old_factory = logging.getLogRecordFactory()


def record_factory(*args, **kwargs):
    record = _old_factory(*args, **kwargs)
    if not hasattr(record, "request_id"):
        record.request_id = get_request_id() or "-"
    if not hasattr(record, "trace_id"):
        record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(record_factory)

logging.config.fileConfig("/app/logging.ini", disable_existing_loggers=False)
logger = logging.getLogger("upload-service")

app = FastAPI(title="Upload Service", version="1.0")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        tid = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
        set_request_id(rid)
        set_trace_id(tid)

        resp: StarletteResponse = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Trace-Id"] = tid
        return resp


app.add_middleware(RequestIdMiddleware)
install_http_metrics(app, "upload-service")

try:
    from web.upload import router as upload_router
except Exception:
    upload_router = None
    logger.exception("failed to import web.upload router")

if upload_router is not None:
    app.include_router(upload_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "service": "upload-service"}