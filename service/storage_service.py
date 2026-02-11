import os
import shutil
from typing import BinaryIO, Optional
from pathlib import Path
import logging

from fastapi import UploadFile

try:
    from src.config import settings
except ImportError:
    class Settings:
        storage_path = None
        storage_type = "local"
    settings = Settings()

logger = logging.getLogger(__name__)


class StorageProvider:
    def save_file(self, file: UploadFile, path: str) -> str:
        raise NotImplementedError

    def get_file(self, path: str) -> BinaryIO:
        raise NotImplementedError

    def delete_file(self, path: str) -> bool:
        raise NotImplementedError

    def file_exists(self, path: str) -> bool:
        raise NotImplementedError

    def get_file_size(self, path: str) -> int:
        raise NotImplementedError

    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        raise NotImplementedError


class LocalStorage(StorageProvider):
    def __init__(self, base_path: Optional[str] = None):
        # ✅ Нормальный дефолт:
        # - если в контейнере есть /app/uploads — используем его
        # - иначе используем ./uploads
        default_path = "/app/uploads" if Path("/app/uploads").exists() else "uploads"
        cfg_path = getattr(settings, "storage_path", None) or default_path
        self.base_path = Path(base_path or cfg_path)

        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage initialized at: {self.base_path}")

    def _get_full_path(self, path: str) -> Path:
        full_path = self.base_path / path
        try:
            full_path.relative_to(self.base_path)
        except ValueError:
            raise ValueError("Invalid path")
        return full_path

    def save_file(self, file: UploadFile, path: str) -> str:
        full_path = self._get_full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return str(full_path)

    def get_file(self, path: str) -> BinaryIO:
        full_path = self._get_full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return open(full_path, "rb")

    def delete_file(self, path: str) -> bool:
        full_path = self._get_full_path(path)
        try:
            full_path.unlink()
            parent = full_path.parent
            while parent != self.base_path and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            return True
        except FileNotFoundError:
            return False

    def file_exists(self, path: str) -> bool:
        return self._get_full_path(path).exists()

    def get_file_size(self, path: str) -> int:
        return self._get_full_path(path).stat().st_size

    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        return f"/api/v1/upload/direct/{path}"


def get_storage_provider() -> StorageProvider:
    storage_type = (getattr(settings, "storage_type", "local") or "local").lower()
    if storage_type == "local":
        return LocalStorage()
    raise ValueError(f"Unknown storage type: {storage_type}")
