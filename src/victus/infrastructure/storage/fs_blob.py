"""Filesystem blob storage: ``<root>/<tenant_id>/<sha[:2]>/<sha256>``.

The storage key stored in ``attachment.storage_key`` is the path relative to
``root`` in POSIX form, so the backup module can copy blobs with
``storage_path / storage_key`` and an archive restores onto any root.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from victus.application.ports.blob_storage import BlobNotFoundError


class FsBlobStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def key_for(tenant_id: str, sha256: str) -> str:
        bad = ("/", "\\", "..")
        if not sha256 or any(b in sha256 for b in bad) or any(b in tenant_id for b in bad):
            raise ValueError("invalid tenant id or hash for a storage key")
        return str(PurePosixPath(tenant_id) / sha256[:2] / sha256)

    def _path(self, storage_key: str) -> Path:
        rel = PurePosixPath(storage_key)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise BlobNotFoundError(storage_key)
        return self.root.joinpath(*rel.parts)

    def put(self, tenant_id: str, sha256: str, data: bytes) -> str:
        key = self.key_for(tenant_id, sha256)
        dest = self._path(key)
        if dest.is_file():
            return key
        dest.parent.mkdir(parents=True, exist_ok=True)
        # write-then-rename so a crash never leaves a half-written blob behind
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp_name, dest)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return key

    def get(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError(storage_key) from exc

    def exists(self, storage_key: str) -> bool:
        try:
            return self._path(storage_key).is_file()
        except BlobNotFoundError:
            return False

    def delete(self, storage_key: str) -> None:
        try:
            self._path(storage_key).unlink(missing_ok=True)
        except BlobNotFoundError:
            return
