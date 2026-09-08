"""Blob storage port for capture attachments (audio, images).

Blobs are addressed by tenant and SHA-256; the storage key returned by
:meth:`BlobStorage.put` is what ``attachment.storage_key`` stores and what the
backup module copies. The filesystem adapter lives in
``infrastructure/storage/fs_blob.py``; tests use an in-memory dict.
"""

from __future__ import annotations

from typing import Protocol


class BlobNotFoundError(FileNotFoundError):
    """The storage key does not resolve to a blob."""


class BlobStorage(Protocol):
    def put(self, tenant_id: str, sha256: str, data: bytes) -> str:
        """Store ``data`` (idempotent for the same hash) and return the storage key."""
        ...

    def get(self, storage_key: str) -> bytes: ...

    def exists(self, storage_key: str) -> bool: ...

    def delete(self, storage_key: str) -> None: ...
