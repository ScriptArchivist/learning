# service/correlation.py

from __future__ import annotations

import uuid
from contextvars import ContextVar

# Храним correlation_id (request_id) / trace_id в контексте текущего запроса/таски
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_request_id() -> str | None:
    return request_id_var.get()


def set_request_id(value: str | None) -> None:
    request_id_var.set(value)


def get_trace_id() -> str | None:
    return trace_id_var.get()


def set_trace_id(value: str | None) -> None:
    trace_id_var.set(value)


def ensure_request_id(existing: str | None = None) -> str:
    rid = existing or get_request_id()
    if rid:
        return rid
    rid = str(uuid.uuid4())
    set_request_id(rid)
    return rid


def ensure_trace_id(existing: str | None = None) -> str:
    tid = existing or get_trace_id()
    if tid:
        return tid
    tid = str(uuid.uuid4())
    set_trace_id(tid)
    return tid


def set_correlation(*, request_id: str | None, trace_id: str | None) -> None:
    """
    Удобный хелпер для worker/publisher:
    выставляет значения в contextvars.
    """
    if request_id is not None:
        set_request_id(request_id)
    if trace_id is not None:
        set_trace_id(trace_id)