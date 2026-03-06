# db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base
from src.config import settings


def _connect_args(url: str, app_name: str | None = None) -> dict:
    # SQLite
    if url.startswith("sqlite"):
        return {"check_same_thread": False}

    # Postgres
    args: dict = {}
    if app_name and (url.startswith("postgresql") or url.startswith("postgres")):
        args["application_name"] = app_name
    return args


def _make_engine(url: str, app_name: str):
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args=_connect_args(url, app_name),
    )


# master (write)
engine_write = _make_engine(settings.database_write_url, "app_writer")
SessionLocalWrite = sessionmaker(bind=engine_write, autocommit=False, autoflush=False)

# replica (read)
engine_read = _make_engine(settings.database_read_url, "app_reader")
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
    # старый get_db — write/master
    yield from get_db_write()


def get_session():
    return get_db()