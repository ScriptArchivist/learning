# db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base  # ✅ один Base на весь проект
from src.config import settings


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


# ✅ master (write)
engine_write = create_engine(
    settings.database_write_url,
    pool_pre_ping=True,
    connect_args=_connect_args(settings.database_write_url),
)

SessionLocalWrite = sessionmaker(
    bind=engine_write,
    autocommit=False,
    autoflush=False,
)

# ✅ replica (read)
engine_read = create_engine(
    settings.database_read_url,
    pool_pre_ping=True,
    connect_args=_connect_args(settings.database_read_url),
)

SessionLocalRead = sessionmaker(
    bind=engine_read,
    autocommit=False,
    autoflush=False,
)

# ✅ backward compatibility: старый SessionLocal оставим как WRITE
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


# ✅ backward compatibility: старый get_db оставим как WRITE
def get_db():
    yield from get_db_write()


def get_session():
    return get_db()
