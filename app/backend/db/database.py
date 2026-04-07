# db/database.py
from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from db.base import Base
from src.config import settings
from src.metrics import (
    dec_db_checked_out,
    get_service_name,
    inc_db_checked_out,
    inc_db_connect,
    inc_db_error,
)


def _connect_args(url: str, app_name: str | None = None) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}

    args: dict = {}
    if app_name and (url.startswith("postgresql") or url.startswith("postgres")):
        args["application_name"] = app_name
    return args


def _pool_size() -> int:
    return int(os.getenv("DB_POOL_SIZE", "5"))


def _max_overflow() -> int:
    return int(os.getenv("DB_MAX_OVERFLOW", "10"))


def _pool_timeout() -> int:
    return int(os.getenv("DB_POOL_TIMEOUT", "30"))


def _make_engine(url: str, app_name: str):
    if url.startswith("sqlite"):
        return create_engine(
            url,
            pool_pre_ping=True,
            connect_args=_connect_args(url, app_name),
        )

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=_pool_size(),
        max_overflow=_max_overflow(),
        pool_timeout=_pool_timeout(),
        connect_args=_connect_args(url, app_name),
    )


def _attach_engine_metrics(engine, *, role: str) -> None:
    service_name = get_service_name("app")

    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        inc_db_connect(service_name, role)

    @event.listens_for(engine, "checkout")
    def on_checkout(dbapi_connection, connection_record, connection_proxy):
        inc_db_checked_out(service_name, role)

    @event.listens_for(engine, "checkin")
    def on_checkin(dbapi_connection, connection_record):
        dec_db_checked_out(service_name, role)

    @event.listens_for(engine, "handle_error")
    def on_handle_error(exception_context):
        exc = exception_context.original_exception
        error_type = type(exc).__name__ if exc is not None else "UnknownError"
        inc_db_error(service_name, role, error_type)


# master (write)
engine_write = _make_engine(settings.database_write_url, "app_writer")
_attach_engine_metrics(engine_write, role="write")
SessionLocalWrite = sessionmaker(bind=engine_write, autocommit=False, autoflush=False)

# replica (read)
engine_read = _make_engine(settings.database_read_url, "app_reader")
_attach_engine_metrics(engine_read, role="read")
SessionLocalRead = sessionmaker(bind=engine_read, autocommit=False, autoflush=False)

# backward compatibility
SessionLocal = SessionLocalWrite
engine = engine_write


def get_db_write():
    db = SessionLocalWrite()
    try:
        yield db
    finally:
        db.close()


def get_db_read():
    db = SessionLocalRead()
    try:
        yield db
    finally:
        db.close()


def get_db():
    yield from get_db_write()


def get_session():
    return get_db()