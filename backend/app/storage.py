"""Attachment storage: local disk for development, a private Cloud Storage bucket in the cloud."""

import hashlib
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings
from app.errors import DomainError

ALLOWED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

# File signatures, so a renamed executable can't pass as a PDF.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".doc": (b"\xd0\xcf\x11\xe0",),
    ".xls": (b"\xd0\xcf\x11\xe0",),
    ".msg": (b"\xd0\xcf\x11\xe0",),
}


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise DomainError("Invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class GcsStorage:
    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily: only needed in the cloud

        self.bucket = storage.Client().bucket(bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "gcs":
        if not s.gcs_bucket:
            raise RuntimeError("ACCORD_GCS_BUCKET is required for the gcs storage backend")
        return GcsStorage(s.gcs_bucket)
    return LocalStorage(s.storage_local_path)


@dataclass
class StoredFile:
    key: str
    filename: str
    content_type: str
    size: int
    sha256: str


def validate_and_store(filename: str, data: bytes, prefix: str) -> StoredFile:
    settings = get_settings()
    safe_name = os.path.basename(filename or "file").strip() or "file"
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_TYPES:
        raise DomainError("That file type isn't accepted. Use PDF, an image, Word, Excel or an email file.", "file_type")
    if not data:
        raise DomainError("The file is empty.", "file_empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise DomainError(f"Files must be under {settings.max_upload_mb} MB.", "file_too_large")
    signatures = _MAGIC.get(ext)
    if signatures and not any(data.startswith(sig) for sig in signatures):
        raise DomainError("The file contents don't match its type.", "file_mismatch")
    key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    content_type = ALLOWED_TYPES[ext]
    get_storage().put(key, data, content_type)
    return StoredFile(key, safe_name[:255], content_type, len(data), hashlib.sha256(data).hexdigest())
