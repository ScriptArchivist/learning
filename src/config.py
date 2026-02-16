# src/config.py
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/app"
    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    storage_type: str = "local"
    storage_path: str = "uploads"

    class Config:
        env_file = ".env"

settings = Settings()


RABBIT_URL = os.getenv("RABBIT_URL", "amqp://guest:guest@localhost:5672/")
RABBIT_QUEUE = os.getenv("RABBIT_QUEUE", "video.process")

# ===== Redis (locks) =====
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
VIDEO_LOCK_TTL_SECONDS = int(os.getenv("VIDEO_LOCK_TTL_SECONDS", "3600"))

# ===== Public HLS URL (served by nginx/CDN) =====
HLS_PUBLIC_BASE_URL = os.getenv("HLS_PUBLIC_BASE_URL", "https://domain").rstrip("/")
HLS_PUBLIC_PATH_PREFIX = os.getenv("HLS_PUBLIC_PATH_PREFIX", "/hls").strip("/")


# ===== Domain events (completed / failed) =====
RABBIT_EVENTS_EXCHANGE = os.getenv("RABBIT_EVENTS_EXCHANGE", "video.events.x")
RABBIT_EVENTS_QUEUE = os.getenv("RABBIT_EVENTS_QUEUE", "video.events")
RABBIT_EVENTS_ROUTING_KEY = os.getenv("RABBIT_EVENTS_ROUTING_KEY", "video.events")
