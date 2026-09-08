"""``manifest.json`` of a backup archive (``schemas/backup-manifest.schema.json``)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
SNAPSHOT_NAME = "snapshot/victus.db"


class ManifestError(ValueError):
    """The manifest is missing, malformed or does not match the archive."""


@dataclass(slots=True)
class TableEntry:
    name: str
    rows: int
    file: str
    sha256: str


@dataclass(slots=True)
class BlobEntry:
    sha256: str
    size: int
    mime: str
    file: str


@dataclass(slots=True)
class SnapshotEntry:
    file: str
    sha256: str
    size: int


@dataclass(slots=True)
class TenantEntry:
    id: str
    slug: str
    name: str | None = None


@dataclass(slots=True)
class Manifest:
    victus_version: str
    schema_revision: str
    created_at: datetime
    tenant: TenantEntry | None
    tables: list[TableEntry] = field(default_factory=list)
    blobs: list[BlobEntry] = field(default_factory=list)
    includes_sqlite_snapshot: bool = False
    sqlite_snapshot: SnapshotEntry | None = None
    sha256_total: str = ""
    database_dialect: str | None = None
    notes: str | None = None
    manifest_version: int = MANIFEST_VERSION

    # ── (de)serialisation ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "manifest_version": self.manifest_version,
            "victus_version": self.victus_version,
            "schema_revision": self.schema_revision,
            "created_at": self.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tenant": None if self.tenant is None else _drop_none(asdict(self.tenant)),
            "tables": [asdict(t) for t in self.tables],
            "blobs": [asdict(b) for b in self.blobs],
            "includes_sqlite_snapshot": self.includes_sqlite_snapshot,
            "sha256_total": self.sha256_total,
        }
        if self.database_dialect:
            d["database_dialect"] = self.database_dialect
        if self.sqlite_snapshot is not None:
            d["sqlite_snapshot"] = asdict(self.sqlite_snapshot)
        if self.notes:
            d["notes"] = self.notes
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Manifest:
        try:
            if d.get("manifest_version") != MANIFEST_VERSION:
                raise ManifestError(f"unsupported manifest_version {d.get('manifest_version')!r}")
            tenant_raw = d.get("tenant")
            tenant = (
                None
                if tenant_raw is None
                else TenantEntry(
                    id=str(tenant_raw["id"]),
                    slug=str(tenant_raw["slug"]),
                    name=tenant_raw.get("name"),
                )
            )
            snap_raw = d.get("sqlite_snapshot")
            snapshot = (
                None
                if snap_raw is None
                else SnapshotEntry(
                    file=str(snap_raw["file"]),
                    sha256=str(snap_raw["sha256"]),
                    size=int(snap_raw["size"]),
                )
            )
            return cls(
                victus_version=str(d["victus_version"]),
                schema_revision=str(d["schema_revision"]),
                created_at=_parse_ts(str(d["created_at"])),
                tenant=tenant,
                tables=[
                    TableEntry(
                        name=str(t["name"]),
                        rows=int(t["rows"]),
                        file=str(t["file"]),
                        sha256=str(t["sha256"]),
                    )
                    for t in d.get("tables", [])
                ],
                blobs=[
                    BlobEntry(
                        sha256=str(b["sha256"]),
                        size=int(b["size"]),
                        mime=str(b["mime"]),
                        file=str(b.get("file") or f"blobs/{b['sha256']}"),
                    )
                    for b in d.get("blobs", [])
                ],
                includes_sqlite_snapshot=bool(d.get("includes_sqlite_snapshot", False)),
                sqlite_snapshot=snapshot,
                sha256_total=str(d.get("sha256_total", "")),
                database_dialect=d.get("database_dialect"),
                notes=d.get("notes"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"malformed manifest: {exc}") from exc

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError("manifest must be a JSON object")
        return cls.from_dict(data)

    # ── integrity ────────────────────────────────────────────────────────

    def file_hashes(self) -> dict[str, str]:
        """Archive member → expected sha256, for everything except the manifest itself."""
        hashes = {t.file: t.sha256 for t in self.tables}
        hashes.update({b.file: b.sha256 for b in self.blobs})
        if self.sqlite_snapshot is not None:
            hashes[self.sqlite_snapshot.file] = self.sqlite_snapshot.sha256
        return hashes

    def compute_total(self) -> str:
        return total_hash(self.file_hashes().values())

    @property
    def scope_label(self) -> str:
        return self.tenant.slug if self.tenant is not None else "all"


def total_hash(hashes: Any) -> str:
    """sha256 over the sorted list of member hashes — quick integrity check."""
    joined = "\n".join(sorted(str(h) for h in hashes)).encode("ascii")
    return hashlib.sha256(joined).hexdigest()


def _parse_ts(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}
