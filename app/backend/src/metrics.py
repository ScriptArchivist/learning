from __future__ import annotations

import inspect
import os
import time
from contextlib import contextmanager
from typing import Awaitable, Callable

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
from starlette.routing import BaseRoute

try:
    from fastapi.routing import APIRoute
except Exception:  # pragma: no cover
    APIRoute = None


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

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "app_http_requests_in_progress",
    "HTTP requests currently in progress",
    ["service", "method", "path"],
)

HTTP_5XX = Counter(
    "app_http_5xx",
    "Total HTTP 5xx responses",
    ["service", "method", "path", "status"],
)

HTTP_EXCEPTIONS = Counter(
    "app_http_exceptions",
    "Unhandled HTTP exceptions",
    ["service", "method", "path", "error_type"],
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

WORKER_JOBS_TOTAL = Counter(
    "app_worker_jobs",
    "Total worker jobs",
    ["service", "job_type", "status"],
)

# ---------------------------
# Broker / queues
# ---------------------------

BROKER_MESSAGES_PUBLISHED = Counter(
    "app_broker_messages_published",
    "Total published broker messages",
    ["service", "event_type", "destination"],
)

BROKER_MESSAGES_CONSUMED = Counter(
    "app_broker_messages_consumed",
    "Total consumed broker messages",
    ["service", "queue", "event_type"],
)

BROKER_CONSUMER_ERRORS = Counter(
    "app_broker_consumer_errors",
    "Broker consumer errors",
    ["service", "queue", "error_type"],
)

BROKER_RETRIES = Counter(
    "app_broker_retries",
    "Broker retries triggered by consumers",
    ["service", "queue"],
)

# ---------------------------
# Outbox / domain
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

OUTBOX_PUBLISH_ATTEMPTS = Counter(
    "app_outbox_publish_attempts",
    "Outbox publish attempts",
    ["service", "event_type"],
)

OUTBOX_PUBLISHED_TOTAL = Counter(
    "app_outbox_published",
    "Outbox published events",
    ["service", "event_type"],
)

LIVE_ACTIVE_SESSIONS = Gauge(
    "app_live_active_sessions",
    "Currently active live sessions",
    ["service"],
)

VIDEO_UPLOADS_TOTAL = Counter(
    "app_video_uploads",
    "Video upload completions",
    ["service", "status"],
)

VIDEO_PROCESSING_TOTAL = Counter(
    "app_video_processing",
    "Video processing pipeline events",
    ["service", "stage"],
)

AUTH_LOGIN_TOTAL = Counter(
    "app_auth_login_total",
    "Total login attempts",
    ["service", "status"],
)

AUTH_LOGIN_DURATION = Histogram(
    "app_auth_login_duration_seconds",
    "Login request duration",
    ["service", "status"],
)

DLQ_REPLAY_TOTAL = Counter(
    "app_dlq_replayed",
    "Total replayed DLQ/outbox failed records",
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

DB_REPLICA_ROW_COUNT = Gauge(
    "app_db_replica_row_count",
    "Row count sampled from DB role for replica drift checks",
    ["service", "role", "entity"],
)

DB_REPLICA_ROW_COUNT_DIFFERENCE = Gauge(
    "app_db_replica_row_count_difference",
    "Absolute row-count difference between master and replica",
    ["service", "entity"],
)


def _normalize_path(path: str | None) -> str:
    if not path:
        return "/"
    if not path.startswith("/"):
        return f"/{path}"
    return path


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None:
        path = getattr(route, "path", None)
        if path:
            return _normalize_path(path)
    return _normalize_path(request.url.path)


def _iter_api_route_templates(app: FastAPI) -> list[tuple[str, list[str]]]:
    result: list[tuple[str, list[str]]] = []

    for route in app.routes:
        if APIRoute is not None and isinstance(route, APIRoute):
            path = _normalize_path(getattr(route, "path", "/"))
            methods = sorted(
                method
                for method in (route.methods or set())
                if method not in {"HEAD", "OPTIONS"}
            )
            if methods:
                result.append((path, methods))
            continue

        if isinstance(route, BaseRoute):
            path = _normalize_path(getattr(route, "path", "/"))
            methods = sorted(
                method
                for method in (getattr(route, "methods", None) or set())
                if method not in {"HEAD", "OPTIONS"}
            )
            if methods:
                result.append((path, methods))

    return result


def _prewarm_http_metrics(app: FastAPI, service_name: str) -> None:
    for path, methods in _iter_api_route_templates(app):
        if path == "/metrics":
            continue

        for method in methods:
            HTTP_REQUESTS.labels(
                service=service_name,
                method=method,
                path=path,
                status="200",
            ).inc(0)

            HTTP_5XX.labels(
                service=service_name,
                method=method,
                path=path,
                status="500",
            ).inc(0)

            HTTP_REQUESTS_IN_PROGRESS.labels(
                service=service_name,
                method=method,
                path=path,
            ).set(0)

            # Для Histogram одного labels() достаточно, чтобы child был создан
            HTTP_REQUEST_DURATION.labels(
                service=service_name,
                method=method,
                path=path,
            )


async def _run_refresh_callback(
    refresh_callback: Callable[[], None] | Callable[[], Awaitable[None]] | None,
) -> None:
    if refresh_callback is None:
        return

    result = refresh_callback()
    if inspect.isawaitable(result):
        await result


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next):
        path = _route_path(request)
        method = request.method.upper()

        if path == "/metrics":
            return await call_next(request)

        in_progress = HTTP_REQUESTS_IN_PROGRESS.labels(
            service=self.service_name,
            method=method,
            path=path,
        )
        in_progress.inc()

        start = time.perf_counter()

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
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

            HTTP_EXCEPTIONS.labels(
                service=self.service_name,
                method=method,
                path=path,
                error_type=type(exc).__name__,
            ).inc()
            raise
        finally:
            in_progress.dec()

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
    refresh_callback: Callable[[], None] | Callable[[], Awaitable[None]] | None = None,
) -> None:
    app.add_middleware(PrometheusMiddleware, service_name=service_name)

    @app.on_event("startup")
    async def _metrics_startup() -> None:
        _prewarm_http_metrics(app, service_name)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        try:
            await _run_refresh_callback(refresh_callback)
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

        WORKER_JOBS_TOTAL.labels(
            service=service_name,
            job_type=job_type,
            status="failed",
        ).inc()

        raise
    else:
        duration = time.perf_counter() - start

        WORKER_JOB_DURATION.labels(
            service=service_name,
            job_type=job_type,
            status="success",
        ).observe(duration)

        WORKER_JOBS_TOTAL.labels(
            service=service_name,
            job_type=job_type,
            status="success",
        ).inc()
    finally:
        WORKER_JOBS_IN_PROGRESS.labels(service=service_name, job_type=job_type).dec()


def set_outbox_backlog(service_name: str, value: int) -> None:
    OUTBOX_BACKLOG.labels(service=service_name).set(value)


def set_outbox_failed(service_name: str, value: int) -> None:
    OUTBOX_FAILED.labels(service=service_name).set(value)


def inc_outbox_publish_attempt(service_name: str, event_type: str) -> None:
    OUTBOX_PUBLISH_ATTEMPTS.labels(service=service_name, event_type=event_type).inc()


def inc_outbox_published(service_name: str, event_type: str) -> None:
    OUTBOX_PUBLISHED_TOTAL.labels(service=service_name, event_type=event_type).inc()


def set_live_active_sessions(service_name: str, value: int) -> None:
    LIVE_ACTIVE_SESSIONS.labels(service=service_name).set(value)


def inc_video_upload(service_name: str, status: str) -> None:
    VIDEO_UPLOADS_TOTAL.labels(service=service_name, status=status).inc()


def inc_video_processing(service_name: str, stage: str) -> None:
    VIDEO_PROCESSING_TOTAL.labels(service=service_name, stage=stage).inc()


def inc_db_connect(service_name: str, role: str) -> None:
    DB_POOL_CONNECTS.labels(service=service_name, role=role).inc()


def inc_db_checked_out(service_name: str, role: str) -> None:
    DB_POOL_CHECKED_OUT.labels(service=service_name, role=role).inc()


def dec_db_checked_out(service_name: str, role: str) -> None:
    DB_POOL_CHECKED_OUT.labels(service=service_name, role=role).dec()


def inc_db_error(service_name: str, role: str, error_type: str) -> None:
    DB_ERRORS.labels(service=service_name, role=role, error_type=error_type).inc()


def set_replica_row_count(service_name: str, role: str, entity: str, value: int) -> None:
    DB_REPLICA_ROW_COUNT.labels(service=service_name, role=role, entity=entity).set(value)


def set_replica_row_diff(service_name: str, entity: str, value: int) -> None:
    DB_REPLICA_ROW_COUNT_DIFFERENCE.labels(service=service_name, entity=entity).set(value)


def inc_broker_published(service_name: str, event_type: str, destination: str) -> None:
    BROKER_MESSAGES_PUBLISHED.labels(
        service=service_name,
        event_type=event_type,
        destination=destination,
    ).inc()


def inc_broker_consumed(service_name: str, queue: str, event_type: str) -> None:
    BROKER_MESSAGES_CONSUMED.labels(
        service=service_name,
        queue=queue,
        event_type=event_type,
    ).inc()


def inc_broker_consumer_error(service_name: str, queue: str, error_type: str) -> None:
    BROKER_CONSUMER_ERRORS.labels(
        service=service_name,
        queue=queue,
        error_type=error_type,
    ).inc()


def inc_broker_retry(service_name: str, queue: str) -> None:
    BROKER_RETRIES.labels(service=service_name, queue=queue).inc()


def inc_dlq_replayed(service_name: str, count: int = 1) -> None:
    DLQ_REPLAY_TOTAL.labels(service=service_name).inc(count)


def get_service_name(default: str) -> str:
    return os.getenv("SERVICE_NAME", default)


def inc_auth_login(service_name: str, status: str) -> None:
    AUTH_LOGIN_TOTAL.labels(service=service_name, status=status).inc()


def observe_auth_login_duration(service_name: str, status: str, duration: float) -> None:
    AUTH_LOGIN_DURATION.labels(service=service_name, status=status).observe(duration)