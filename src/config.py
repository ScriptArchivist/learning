# src/config.py
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # master (write)
    database_write_url: str = "postgresql+psycopg://postgres:postgres@db-master:5432/app"

    # replica (read)
    # если не задано — читаем тоже из master
    database_read_url: str | None = None

    @property
    def database_url(self) -> str:
        # backward compatibility для старого кода
        return self.database_write_url

    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    storage_type: str = "local"
    storage_path: str = "uploads"

    # delivery/origin mode
    DELIVERY_MODE: str = "local"  # local | url
    DELIVERY_BASE_URL: str = "http://origin"  # internal (containers)
    DELIVERY_PUBLIC_BASE_URL: str = "http://localhost:8080"  # external (for clients)

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()

if not settings.database_read_url:
    settings.database_read_url = settings.database_write_url


# ===== Rabbit =====
RABBIT_URL = os.getenv("RABBIT_URL", "amqp://guest:guest@localhost:5672/")
RABBIT_QUEUE = os.getenv("RABBIT_QUEUE", "video.process")

# ===== Redis =====
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
VIDEO_LOCK_TTL_SECONDS = int(os.getenv("VIDEO_LOCK_TTL_SECONDS", "3600"))

# ===== Domain events =====
RABBIT_EVENTS_EXCHANGE = os.getenv("RABBIT_EVENTS_EXCHANGE", "video.events.x")
RABBIT_EVENTS_QUEUE = os.getenv("RABBIT_EVENTS_QUEUE", "events.q")
RABBIT_EVENTS_ROUTING_KEY = os.getenv("RABBIT_EVENTS_ROUTING_KEY", "video.events")

# ===== Public HLS URL (served by nginx/origin/CDN) =====
HLS_PUBLIC_BASE_URL = (
    os.getenv("HLS_PUBLIC_BASE_URL")
    or os.getenv("DELIVERY_PUBLIC_BASE_URL")
    or os.getenv("ORIGIN_BASE_URL")
    or "http://localhost:8080"
).rstrip("/")
HLS_PUBLIC_PATH_PREFIX = (os.getenv("HLS_PUBLIC_PATH_PREFIX") or "hls").strip("/")

# ===== Backward compatibility for old modules =====
DELIVERY_MODE = os.getenv("DELIVERY_MODE", settings.DELIVERY_MODE)
DELIVERY_BASE_URL = os.getenv("DELIVERY_BASE_URL", settings.DELIVERY_BASE_URL).rstrip("/")
ORIGIN_BASE_URL = os.getenv("ORIGIN_BASE_URL", settings.DELIVERY_PUBLIC_BASE_URL).rstrip("/")