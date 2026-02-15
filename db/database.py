# db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.base import Base  # ✅ один Base на весь проект


try:
    from src.config import settings
    DATABASE_URL = settings.database_url
except ImportError:
    DATABASE_URL = "postgresql+psycopg://postgres:postgres@db:5432/app"

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_session():
    return get_db()
