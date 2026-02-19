# src/config.py
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ✅ Pydantic v2: настройка чтения env
    # extra="ignore" — ключевой фикс: любые лишние переменные из .env/docker-compose не будут валить приложение
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/app"
    secret_key: str = "changeme"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    storage_type: str = "local"   # local | s3 (позже)
    storage_path: str = "uploads"

    # ✅ пункт 4: delivery/origin mode
    DELIVERY_MODE: str = "local"  # local | url
    DELIVERY_BASE_URL: str = "http://localhost:8080"

    # ✅ S3/MinIO (пока не используем, но переменные уже могут быть в .env / compose)
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_upload_url_expires_seconds: int = 900


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

# ===== параметры delivery =====
DELIVERY_MODE = os.getenv("DELIVERY_MODE", "local")  # local | url
DELIVERY_BASE_URL = os.getenv("DELIVERY_BASE_URL", "http://localhost:8080").rstrip("/")
