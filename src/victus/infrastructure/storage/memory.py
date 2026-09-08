"""In-memory blob storage for tests."""

from __future__ import annotations

from victus.application.ports.blob_storage import BlobNotFoundError


class InMemoryBlobStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put(self, tenant_id: str, sha256: str, data: bytes) -> str:
        key = f"{tenant_id}/{sha256[:2]}/{sha256}"
        self.blobs.setdefault(key, bytes(data))
        return key

    def get(self, storage_key: str) -> bytes:
        try:
            return self.blobs[storage_key]
        except KeyError as exc:
            raise BlobNotFoundError(storage_key) from exc

    def exists(self, storage_key: str) -> bool:
        return storage_key in self.blobs

    def delete(self, storage_key: str) -> None:
        self.blobs.pop(storage_key, None)
