"""Export-file storage abstraction.

Bulk exports are written here as ``.csv.gz`` files. A ``LocalDisk`` backend
(under ``settings.reports_dir``) is used today; an S3/MinIO backend can drop in
behind the same interface later without touching the worker or service.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import BinaryIO

from app.core.config import settings


class Storage(ABC):
    """Minimal blob store keyed by a relative object key (e.g. "abc.csv.gz")."""

    @abstractmethod
    def open_write(self, key: str) -> BinaryIO:
        """Open a binary file handle to stream bytes into."""

    @abstractmethod
    def open_read(self, key: str) -> BinaryIO:
        """Open a binary file handle to read bytes from."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def locator(self, key: str) -> str:
        """An opaque locator persisted on the job (a path now, a URI later)."""


class LocalDiskStorage(Storage):
    """Stores objects as files under ``base_dir`` (default: settings.reports_dir)."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = base_dir or settings.reports_dir

    def _path(self, key: str) -> str:
        # Guard against path traversal: keys are flat filenames.
        safe = os.path.basename(key)
        return os.path.join(self.base_dir, safe)

    def open_write(self, key: str) -> BinaryIO:
        os.makedirs(self.base_dir, exist_ok=True)
        return open(self._path(key), "wb")

    def open_read(self, key: str) -> BinaryIO:
        return open(self._path(key), "rb")

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def size(self, key: str) -> int:
        return os.path.getsize(self._path(key))

    def delete(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)

    def locator(self, key: str) -> str:
        return self._path(key)


def get_storage() -> Storage:
    """Return the configured storage backend (LocalDisk today)."""
    return LocalDiskStorage()
