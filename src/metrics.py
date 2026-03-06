# src/metrics.py
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------
# HTTP
# ---------------------------

HTTP_REQUESTS = Counter(
    "app_http_requests",
    "Total HTTP requests",
    ["service", "method", "path", "status"],
)

HTTP_REQUEST_DURATION = Histogram(
    "app_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "method", "path"],
)

HTTP_5XX = Counter(
    "app_http_5xx",
    "Total HTTP 5xx responses",
    ["service", "method", "path", "status"],
)

# ---------------------------
# Worker / background jobs
# ---------------------------

WORKER_JOBS_IN_PROGRESS = Gauge(
    "app_worker_jobs_in_progress",
    "Worker jobs currently in progress",
    ["service", "job_type"],
)

WORKER_JOB_DURATION = Histogram(
    "app_worker_job_duration_seconds",
    "Worker job duration in seconds",
    ["service", "job_type", "status"],
)

WORKER_JOB_FAILURES = Counter(
    "app_worker_job_failures",
    "Total worker job failures",
    ["service", "job_type", "error_type"],
)

# ---------------------------
# Domain gauges
# ---------------------------

OUTBOX_BACKLOG = Gauge(
    "app_outbox_backlog",
    "Outbox events waiting to be published",
    ["service"],
)

OUTBOX_FAILED = Gauge(
    "app_outbox_failed",
    "Outbox events in FAILED state",
    ["service"],
)

LIVE_ACTIVE_SESSIONS = Gauge(
    "app_live_active_sessions",
    "Currently active live sessions",
    ["service"],
)

# ---------------------------
# DB
# ---------------------------

DB_POOL_CHECKED_OUT = Gauge(
    "app_db_pool_checked_out",
    "Checked out DB connections",
    ["service", "role"],
)

DB_POOL_CONNECTS = Counter(
    "app_db_pool_connects",
    "Total DB connects",
    ["service", "role"],
)

DB_ERRORS = Counter(
    "app_db_errors",
    "Total DB errors",
    ["service", "role", "error_type"],
)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None:
        path = getattr(route, "path", None)
        if path:
            return path
    return request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next):
        path = _route_path(request)
        method = request.method

        start = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration = time.perf_counter() - start
            HTTP_REQUEST_DURATION.labels(
                service=self.service_name,
                method=method,
                path=path,
            ).observe(duration)

            HTTP_REQUESTS.labels(
                service=self.service_name,
                method=method,
                path=path,
                status="500",
            ).inc()

            HTTP_5XX.labels(
                service=self.service_name,
                method=method,
                path=path,
                status="500",
            ).inc()
            raise

        duration = time.perf_counter() - start

        HTTP_REQUEST_DURATION.labels(
            service=self.service_name,
            method=method,
            path=path,
        ).observe(duration)

        HTTP_REQUESTS.labels(
            service=self.service_name,
            method=method,
            path=path,
            status=str(status_code),
        ).inc()

        if status_code >= 500:
            HTTP_5XX.labels(
                service=self.service_name,
                method=method,
                path=path,
                status=str(status_code),
            ).inc()

        return response


def install_http_metrics(
    app: FastAPI,
    service_name: str,
    refresh_callback: Callable[[], None] | None = None,
) -> None:
    app.add_middleware(PrometheusMiddleware, service_name=service_name)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        if refresh_callback is not None:
            try:
                refresh_callback()
            except Exception:
                # /metrics не должен падать из-за refresh callback
                pass
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def start_background_metrics_server(port: int) -> None:
    start_http_server(port)


@contextmanager
def track_job(service_name: str, job_type: str):
    WORKER_JOBS_IN_PROGRESS.labels(service=service_name, job_type=job_type).inc()
    start = time.perf_counter()

    try:
        yield
    except Exception as exc:
        duration = time.perf_counter() - start

        WORKER_JOB_FAILURES.labels(
            service=service_name,
            job_type=job_type,
            error_type=type(exc).__name__,
        ).inc()

        WORKER_JOB_DURATION.labels(
            service=service_name,
            job_type=job_type,
            status="failed",
        ).observe(duration)

        raise
    else:
        duration = time.perf_counter() - start
        WORKER_JOB_DURATION.labels(
            service=service_name,
            job_type=job_type,
            status="success",
        ).observe(duration)
    finally:
        WORKER_JOBS_IN_PROGRESS.labels(service=service_name, job_type=job_type).dec()


def set_outbox_backlog(service_name: str, value: int) -> None:
    OUTBOX_BACKLOG.labels(service=service_name).set(value)


def set_outbox_failed(service_name: str, value: int) -> None:
    OUTBOX_FAILED.labels(service=service_name).set(value)


def set_live_active_sessions(service_name: str, value: int) -> None:
    LIVE_ACTIVE_SESSIONS.labels(service=service_name).set(value)


def inc_db_connect(service_name: str, role: str) -> None:
    DB_POOL_CONNECTS.labels(service=service_name, role=role).inc()


def inc_db_checked_out(service_name: str, role: str) -> None:
    DB_POOL_CHECKED_OUT.labels(service=service_name, role=role).inc()


def dec_db_checked_out(service_name: str, role: str) -> None:
    DB_POOL_CHECKED_OUT.labels(service=service_name, role=role).dec()


def inc_db_error(service_name: str, role: str, error_type: str) -> None:
    DB_ERRORS.labels(service=service_name, role=role, error_type=error_type).inc()


def get_service_name(default: str) -> str:
    return os.getenv("SERVICE_NAME", default)