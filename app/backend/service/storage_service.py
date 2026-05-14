# service/storage_service.py
import logging
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional

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

    def delete_dir(self, path: str) -> bool:
        raise NotImplementedError

    def resolve_local_path(self, path: str) -> str | None:
        return None

    def download_to_path(self, key: str, local_path: str) -> str:
        raise NotImplementedError

    def upload_file_path(self, local_path: str, key: str, content_type: str | None = None) -> str:
        raise NotImplementedError

    def upload_dir(self, local_dir: str, key_prefix: str) -> None:
        raise NotImplementedError


class LocalStorage(StorageProvider):
    def __init__(self, base_path: Optional[str] = None):
        default_path = "/app/uploads" if Path("/app/uploads").exists() else "uploads"
        cfg_path = getattr(settings, "storage_path", None) or default_path
        self.base_path = Path(base_path or cfg_path)

        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info("Local storage initialized at: %s", self.base_path)

    def _get_full_path(self, path: str) -> Path:
        normalized = path.lstrip("/")
        full_path = (self.base_path / normalized).resolve()
        base = self.base_path.resolve()

        try:
            full_path.relative_to(base)
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
            base = self.base_path.resolve()

            while parent != base and parent.exists() and not any(parent.iterdir()):
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

    def delete_dir(self, path: str) -> bool:
        full_path = self._get_full_path(path)
        if not full_path.exists():
            return False
        if not full_path.is_dir():
            raise ValueError("Not a directory")
        shutil.rmtree(full_path, ignore_errors=True)
        return True

    def resolve_local_path(self, path: str) -> str:
        return str(self._get_full_path(path))

    def download_to_path(self, key: str, local_path: str) -> str:
        src = self._get_full_path(key)
        dst = Path(local_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return str(dst)

    def upload_file_path(self, local_path: str, key: str, content_type: str | None = None) -> str:
        dst = self._get_full_path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dst)
        return str(dst)

    def upload_dir(self, local_dir: str, key_prefix: str) -> None:
        src_dir = Path(local_dir)
        if not src_dir.exists() or not src_dir.is_dir():
            raise FileNotFoundError(f"Directory not found: {local_dir}")

        for src in src_dir.rglob("*"):
            if not src.is_file():
                continue

            rel = src.relative_to(src_dir).as_posix()
            key = f"{key_prefix.strip('/')}/{rel}"
            self.upload_file_path(str(src), key)


class S3Storage(StorageProvider):
    def __init__(self):
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError as e:
            raise RuntimeError(
                "S3 storage requires boto3. Add boto3 to requirements.txt"
            ) from e

        self._client_error = ClientError

        self.bucket = getattr(settings, "s3_bucket", None)
        self.endpoint_url = getattr(settings, "s3_endpoint_url", None)
        self.region_name = getattr(settings, "s3_region_name", None) or "ru-1"
        self.access_key_id = getattr(settings, "s3_access_key_id", None)
        self.secret_access_key = getattr(settings, "s3_secret_access_key", None)

        if not self.bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_TYPE=s3")

        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region_name,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )

        logger.info(
            "S3 storage initialized: bucket=%s endpoint=%s region=%s",
            self.bucket,
            self.endpoint_url,
            self.region_name,
        )

    def _normalize_key(self, key: str) -> str:
        normalized = key.lstrip("/")
        if ".." in Path(normalized).parts:
            raise ValueError("Invalid S3 key")
        return normalized

    def save_file(self, file: UploadFile, path: str) -> str:
        key = self._normalize_key(path)
        extra_args = {}

        if file.content_type:
            extra_args["ContentType"] = file.content_type

        self.client.upload_fileobj(
            file.file,
            self.bucket,
            key,
            ExtraArgs=extra_args or None,
        )
        return key

    def get_file(self, path: str) -> BinaryIO:
        key = self._normalize_key(path)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.close()
        self.client.download_file(self.bucket, key, tmp.name)
        return open(tmp.name, "rb")

    def delete_file(self, path: str) -> bool:
        key = self._normalize_key(path)
        self.client.delete_object(Bucket=self.bucket, Key=key)
        return True

    def file_exists(self, path: str) -> bool:
        key = self._normalize_key(path)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self._client_error as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def get_file_size(self, path: str) -> int:
        key = self._normalize_key(path)
        resp = self.client.head_object(Bucket=self.bucket, Key=key)
        return int(resp["ContentLength"])

    def generate_upload_url(self, path: str, expires_minutes: int = 60) -> str:
        key = self._normalize_key(path)
        return self.client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
            },
            ExpiresIn=int(expires_minutes * 60),
        )

    def delete_dir(self, path: str) -> bool:
        prefix = self._normalize_key(path).rstrip("/") + "/"

        paginator = self.client.get_paginator("list_objects_v2")
        deleted_any = False

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not objects:
                continue

            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": objects},
            )
            deleted_any = True

        return deleted_any

    def resolve_local_path(self, path: str) -> str | None:
        return None

    def download_to_path(self, key: str, local_path: str) -> str:
        normalized = self._normalize_key(key)
        dst = Path(local_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, normalized, str(dst))
        return str(dst)

    def upload_file_path(self, local_path: str, key: str, content_type: str | None = None) -> str:
        normalized = self._normalize_key(key)
        extra_args = {}

        if content_type:
            extra_args["ContentType"] = content_type

        self.client.upload_file(
            Filename=local_path,
            Bucket=self.bucket,
            Key=normalized,
            ExtraArgs=extra_args or None,
        )
        return normalized

    def upload_dir(self, local_dir: str, key_prefix: str) -> None:
        src_dir = Path(local_dir)
        if not src_dir.exists() or not src_dir.is_dir():
            raise FileNotFoundError(f"Directory not found: {local_dir}")

        prefix = self._normalize_key(key_prefix).rstrip("/")

        for src in src_dir.rglob("*"):
            if not src.is_file():
                continue

            rel = src.relative_to(src_dir).as_posix()
            key = f"{prefix}/{rel}"

            content_type = None
            if src.suffix == ".m3u8":
                content_type = "application/vnd.apple.mpegurl"
            elif src.suffix == ".ts":
                content_type = "video/mp2t"

            self.upload_file_path(str(src), key, content_type=content_type)


def get_storage_provider() -> StorageProvider:
    storage_type = (getattr(settings, "storage_type", "local") or "local").lower()

    if storage_type == "local":
        return LocalStorage()

    if storage_type in ("s3", "selectel", "minio"):
        return S3Storage()

    raise ValueError(f"Unknown storage type: {storage_type}")