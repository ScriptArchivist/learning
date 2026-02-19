# src/config.py
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ✅ Пункт 6: master/replica
    # master (write)
    database_write_url: str = "postgresql+psycopg://postgres:postgres@db:5432/app"
    # replica (read) — по умолчанию = master, чтобы ничего не ломать
    database_read_url: str | None = None

    # ✅ Backward compatibility (если где-то ещё используется database_url)
    @property
    def database_url(self) -> str:
        return self.database_write_url

    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    storage_type: str = "local"
    storage_path: str = "uploads"

    # ✅ delivery/origin mode
    DELIVERY_MODE: str = "local"  # local | url
    DELIVERY_BASE_URL: str = "http://localhost:8080"

    class Config:
        env_file = ".env"


settings = Settings()

# Если replica не задана — читаем с master
if not settings.database_read_url:
    settings.database_read_url = settings.database_write_url


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

# ===== параметры delivery =====
DELIVERY_MODE = os.getenv("DELIVERY_MODE", "local")  # local | url
DELIVERY_BASE_URL = os.getenv("DELIVERY_BASE_URL", "http://localhost:8080").rstrip("/")
