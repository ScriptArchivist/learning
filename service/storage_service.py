# service/storage_service.py
"""
Абстракция для хранения файлов. Сейчас - локальная файловая система.
Позже заменим на MinIO/S3 без изменения бизнес-логики.
"""

import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import BinaryIO, Optional
from pathlib import Path
import logging

from fastapi import UploadFile

# Импортируем настройки из твоего config.py
try:
    from src.config import settings
except ImportError:
    # Fallback для обратной совместимости
    class Settings:
        storage_path = "uploads"
        storage_type = "local"
    settings = Settings()

logger = logging.getLogger(__name__)

# ========== INTERFACE ==========
class StorageProvider:
    """Абстрактный интерфейс для хранилища."""
    
    def save_file(self, file: UploadFile, path: str) -> str:
        """Сохранить файл."""
        raise NotImplementedError
    
    def get_file(self, path: str) -> BinaryIO:
        """Получить файл для чтения."""
        raise NotImplementedError
    
    def delete_file(self, path: str) -> bool:
        """Удалить файл."""
        raise NotImplementedError
    
    def file_exists(self, path: str) -> bool:
        """Проверить существование файла."""
        raise NotImplementedError
    
    def get_file_size(self, path: str) -> int:
        """Получить размер файла."""
        raise NotImplementedError
    
    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        """Сгенерировать URL для загрузки (для S3/MinIO)."""
        raise NotImplementedError

# ========== LOCAL FILESYSTEM (текущая реализация) ==========
class LocalStorage(StorageProvider):
    """Локальное хранилище в файловой системе."""
    
    def __init__(self, base_path: Optional[str] = None):
        # Используем настройки из config.py или значение по умолчанию
        self.base_path = Path(base_path or settings.storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local storage initialized at: {self.base_path}")
    
    def _get_full_path(self, path: str) -> Path:
        """Получить полный путь к файлу."""
        full_path = self.base_path / path
        # Защита от path traversal атак
        try:
            full_path.relative_to(self.base_path)
        except ValueError:
            raise ValueError("Invalid path")
        return full_path
    
    def save_file(self, file: UploadFile, path: str) -> str:
        """Сохранить файл на диск."""
        full_path = self._get_full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(full_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.debug(f"File saved: {full_path}")
        return str(full_path)
    
    def get_file(self, path: str) -> BinaryIO:
        """Открыть файл для чтения."""
        full_path = self._get_full_path(path)
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return open(full_path, "rb")
    
    def delete_file(self, path: str) -> bool:
        """Удалить файл."""
        full_path = self._get_full_path(path)
        try:
            full_path.unlink()
            # Удаляем пустые директории
            parent = full_path.parent
            while parent != self.base_path and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
            logger.debug(f"File deleted: {full_path}")
            return True
        except FileNotFoundError:
            logger.warning(f"File not found for deletion: {path}")
            return False
    
    def file_exists(self, path: str) -> bool:
        """Проверить существование файла."""
        full_path = self._get_full_path(path)
        return full_path.exists()
    
    def get_file_size(self, path: str) -> int:
        """Получить размер файла."""
        full_path = self._get_full_path(path)
        return full_path.stat().st_size
    
    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        """Для локального хранилища возвращаем endpoint для загрузки."""
        # В локальном режиме используем обычный POST endpoint
        return f"/api/v1/upload/direct/{path}"

# ========== S3/MINIO (заглушка для будущей реализации) ==========
class S3Storage(StorageProvider):
    """Хранилище в S3/MinIO (заглушка)."""
    
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        logger.info(f"S3Storage initialized for bucket: {bucket}")
    
    def save_file(self, file: UploadFile, path: str) -> str:
        """Временная реализация: сохраняем локально, но логируем для S3."""
        logger.info(f"[S3 MOCK] Would save to s3://{self.bucket}/{path}")
        
        # Временно сохраняем локально в папку из настроек
        local_storage = LocalStorage()
        return local_storage.save_file(file, path)
    
    def get_file(self, path: str) -> BinaryIO:
        logger.info(f"[S3 MOCK] Would get from s3://{self.bucket}/{path}")
        local_storage = LocalStorage()
        return local_storage.get_file(path)
    
    def delete_file(self, path: str) -> bool:
        logger.info(f"[S3 MOCK] Would delete from s3://{self.bucket}/{path}")
        local_storage = LocalStorage()
        return local_storage.delete_file(path)
    
    def file_exists(self, path: str) -> bool:
        logger.info(f"[S3 MOCK] Would check s3://{self.bucket}/{path}")
        local_storage = LocalStorage()
        return local_storage.file_exists(path)
    
    def get_file_size(self, path: str) -> int:
        logger.info(f"[S3 MOCK] Would get size from s3://{self.bucket}/{path}")
        local_storage = LocalStorage()
        return local_storage.get_file_size(path)
    
    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        """Заглушка для генерации presigned URL."""
        logger.info(f"[S3 MOCK] Would generate presigned URL for s3://{self.bucket}/{path}")
        return f"https://{self.endpoint}/{self.bucket}/{path}"

# ========== FACTORY ==========
def get_storage_provider() -> StorageProvider:
    """
    Фабрика для получения хранилища.
    Использует настройки из config.py.
    """
    storage_type = settings.storage_type.lower()
    
    if storage_type == "local":
        return LocalStorage()
    
    elif storage_type in ["s3", "minio"]:
        # Эти параметры можно тоже добавить в settings позже
        return S3Storage(
            endpoint=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
            bucket=os.getenv("S3_BUCKET", "videos")
        )
    
    else:
        raise ValueError(f"Unknown storage type: {storage_type}")

# ========== UTILITY FUNCTIONS ==========
def generate_video_path(user_id: int, video_id: int, filename: str) -> str:
    """Генерирует путь для хранения видео."""
    ext = Path(filename).suffix.lower()
    unique_name = f"{uuid.uuid4()}{ext}"
    return f"original/{user_id}/{video_id}/{unique_name}"

def generate_thumbnail_path(video_path: str) -> str:
    """Генерирует путь для превью на основе пути видео."""
    path = Path(video_path)
    return str(path.parent / f"{path.stem}_thumbnail.jpg")

def generate_format_path(video_path: str, resolution: str, codec: str) -> str:
    """Генерирует путь для транскодированной версии."""
    path = Path(video_path)
    return str(path.parent / f"{path.stem}_{resolution}_{codec}{path.suffix}")

# ========== DIRECT UPLOAD ENDPOINT (для локального хранилища) ==========
async def handle_direct_upload(
    file: UploadFile,
    path: str,
    storage: StorageProvider
) -> bool:
    """Обработать прямую загрузку файла."""
    try:
        storage.save_file(file, path)
        logger.info(f"File uploaded to {path}")
        return True
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return False