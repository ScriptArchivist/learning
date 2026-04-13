from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from identity.web.auth import router as auth_router
from src.metrics import install_http_metrics
from service.correlation import ensure_request_id, ensure_trace_id, set_correlation


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID")
        trace_id = request.headers.get("X-Trace-ID")

        request_id = ensure_request_id(request_id)
        trace_id = ensure_trace_id(trace_id)

        set_correlation(request_id=request_id, trace_id=trace_id)

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id

        return response


app = FastAPI(
    title="Identity Service",
)

app.add_middleware(CorrelationMiddleware)

install_http_metrics(app, "identity-service")

app.include_router(auth_router)