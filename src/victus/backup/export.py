"""Create a backup archive (streaming; nothing is held in memory as a whole)."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from sqlalchemy import Engine, Table, select

from victus import __version__
from victus.backup.codec import encode_row
from victus.backup.manifest import (
    MANIFEST_NAME,
    SNAPSHOT_NAME,
    BlobEntry,
    Manifest,
    SnapshotEntry,
    TableEntry,
    TenantEntry,
    total_hash,
)
from victus.backup.scoping import export_tables, is_global, tenant_filter
from victus.infrastructure.db.orm import Base
from victus.infrastructure.migrations import runner

ARCHIVE_RE = re.compile(r"^victus-(?P<scope>[a-z0-9-]+|all)-(?P<ts>\d{8}T\d{6}Z)\.zip$")
_BATCH = 1000


class ExportError(RuntimeError):
    pass


@dataclass(slots=True)
class BackupArchive:
    path: Path
    manifest: Manifest
    warnings: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return self.path.stat().st_size


class _HashingWriter:
    """Write-through wrapper computing sha256 and byte count."""

    def __init__(self, fh: IO[bytes]) -> None:
        self._fh = fh
        self.hash = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> None:
        self._fh.write(data)
        self.hash.update(data)
        self.size += len(data)


def archive_name(scope: str, now: datetime) -> str:
    return f"victus-{scope}-{now.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"


def parse_archive_name(path: Path) -> tuple[str, datetime] | None:
    """``(scope, created_at)`` from a file name, or ``None`` if it is not a Victus archive."""
    m = ARCHIVE_RE.match(path.name)
    if not m:
        return None
    ts = datetime.strptime(m.group("ts"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return m.group("scope"), ts


def list_archives(target_dir: Path, scope: str | None = None) -> list[Path]:
    """Victus archives in ``target_dir``, newest first."""
    found: list[tuple[datetime, Path]] = []
    if not target_dir.is_dir():
        return []
    for p in target_dir.iterdir():
        parsed = parse_archive_name(p)
        if parsed is None:
            continue
        if scope is not None and parsed[0] != scope:
            continue
        found.append((parsed[1], p))
    return [p for _, p in sorted(found, reverse=True)]


def _resolve_tenant(engine: Engine, slug: str) -> TenantEntry:
    tenant = Base.metadata.tables["tenant"]
    with engine.connect() as conn:
        row = conn.execute(select(tenant).where(tenant.c.slug == slug)).mappings().first()
    if row is None:
        raise ExportError(f"tenant {slug!r} not found")
    return TenantEntry(id=str(row["id"]), slug=str(row["slug"]), name=row.get("name"))


def _rows(engine: Engine, table: Table, tenant_id: str | None) -> Iterator[dict[str, Any]]:
    stmt = select(table)
    if tenant_id is not None and not is_global(table):
        stmt = stmt.where(tenant_filter(table, tenant_id))
    pk_cols = list(table.primary_key.columns)
    if pk_cols:
        stmt = stmt.order_by(*pk_cols)
    with engine.connect() as conn:
        result = conn.execution_options(yield_per=_BATCH).execute(stmt)
        for row in result.mappings():
            yield dict(row)


def _write_table(
    zf: zipfile.ZipFile, engine: Engine, table: Table, tenant_id: str | None
) -> TableEntry:
    member = f"data/{table.name}.jsonl"
    rows = 0
    with zf.open(member, "w") as fh:
        w = _HashingWriter(fh)
        for row in _rows(engine, table, tenant_id):
            w.write((encode_row(row) + "\n").encode("utf-8"))
            rows += 1
    return TableEntry(name=table.name, rows=rows, file=member, sha256=w.hash.hexdigest())


def _attachments(engine: Engine, tenant_id: str | None) -> list[dict[str, Any]]:
    return list(_rows(engine, Base.metadata.tables["attachment"], tenant_id))


def _write_blobs(
    zf: zipfile.ZipFile, attachments: list[dict[str, Any]], storage_path: Path | None
) -> tuple[list[BlobEntry], list[str]]:
    blobs: list[BlobEntry] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for att in attachments:
        sha = str(att["sha256"])
        if sha in seen:
            continue
        seen.add(sha)
        if storage_path is None:
            warnings.append(f"attachment {sha[:12]}… skipped: no storage path configured")
            continue
        src = storage_path / str(att["storage_key"])
        if not src.is_file():
            warnings.append(f"attachment {sha[:12]}… missing on disk: {src}")
            continue
        member = f"blobs/{sha}"
        digest = hashlib.sha256()
        size = 0
        with src.open("rb") as fsrc, zf.open(member, "w") as fdst:
            zinfo_writer = _HashingWriter(fdst)
            while chunk := fsrc.read(1 << 20):
                zinfo_writer.write(chunk)
            digest = zinfo_writer.hash
            size = zinfo_writer.size
        actual = digest.hexdigest()
        if actual != sha:
            warnings.append(
                f"attachment {sha[:12]}… content hash mismatch on disk ({actual[:12]}…)"
            )
        blobs.append(BlobEntry(sha256=actual, size=size, mime=str(att["mime"]), file=member))
    return blobs, warnings


def _sqlite_file(engine: Engine) -> Path | None:
    if engine.dialect.name != "sqlite":
        return None
    db = engine.url.database
    if not db or db == ":memory:":
        return None
    return Path(db)


def _write_snapshot(zf: zipfile.ZipFile, engine: Engine) -> SnapshotEntry | None:
    if _sqlite_file(engine) is None:
        return None
    with tempfile.TemporaryDirectory(prefix="victus-snapshot-") as tmp:
        target = Path(tmp) / "victus.db"
        # VACUUM cannot run inside a transaction; autocommit connection.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f"VACUUM INTO '{target.as_posix().replace(chr(39), chr(39) * 2)}'")
        digest = hashlib.sha256()
        size = 0
        with target.open("rb") as fsrc, zf.open(SNAPSHOT_NAME, "w") as fdst:
            while chunk := fsrc.read(1 << 20):
                fdst.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    return SnapshotEntry(file=SNAPSHOT_NAME, sha256=digest.hexdigest(), size=size)


def create_backup(
    engine: Engine,
    target_dir: Path,
    tenant_slug: str | None = None,
    *,
    include_sqlite_snapshot: bool = True,
    storage_path: Path | None = None,
    now: datetime | None = None,
) -> BackupArchive:
    """Write ``victus-<tenant|all>-<UTC>.zip`` into ``target_dir`` and return it.

    ``tenant_slug=None`` exports every tenant. Rows are streamed table by table
    in foreign-key order; attachments are copied from ``storage_path``; on a
    file-based SQLite database a ``VACUUM INTO`` snapshot is added unless
    ``include_sqlite_snapshot`` is false.
    """
    now = now or datetime.now(UTC)
    target_dir.mkdir(parents=True, exist_ok=True)
    tenant = _resolve_tenant(engine, tenant_slug) if tenant_slug else None
    tenant_id = tenant.id if tenant else None
    final = target_dir / archive_name(tenant.slug if tenant else "all", now)
    tmp_path = final.with_suffix(".zip.part")

    tables: list[TableEntry] = []
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            for table in export_tables():
                tables.append(_write_table(zf, engine, table, tenant_id))
            blobs, blob_warnings = _write_blobs(zf, _attachments(engine, tenant_id), storage_path)
            warnings.extend(blob_warnings)
            snapshot = _write_snapshot(zf, engine) if include_sqlite_snapshot else None
            manifest = Manifest(
                victus_version=__version__,
                schema_revision=runner.current(engine=engine) or runner.head(),
                created_at=now,
                tenant=tenant,
                tables=tables,
                blobs=blobs,
                includes_sqlite_snapshot=snapshot is not None,
                sqlite_snapshot=snapshot,
                database_dialect=engine.dialect.name,
                notes="; ".join(warnings) or None,
            )
            manifest.sha256_total = total_hash(manifest.file_hashes().values())
            zf.writestr(MANIFEST_NAME, manifest.to_json())
        shutil.move(str(tmp_path), str(final))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return BackupArchive(path=final, manifest=manifest, warnings=warnings)


__all__ = [
    "BackupArchive",
    "ExportError",
    "archive_name",
    "create_backup",
    "list_archives",
    "parse_archive_name",
]
