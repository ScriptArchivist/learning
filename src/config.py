# src/config.py
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
