"""Restore a backup archive into a database — one transaction, counts checked."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, Engine, Table, delete, func, select, text
from sqlalchemy.dialects import postgresql, sqlite

from victus.backup.codec import decode_row
from victus.backup.manifest import MANIFEST_NAME, Manifest, ManifestError
from victus.backup.scoping import export_tables, is_global, tenant_filter
from victus.infrastructure.db.orm import Base
from victus.infrastructure.migrations import runner

RestoreMode = Literal["fail_if_exists", "replace", "merge_new"]
_BATCH = 500


class RestoreError(RuntimeError):
    """Restore refused or failed; the database is unchanged."""


@dataclass(slots=True)
class RestoreResult:
    archive: Path
    mode: RestoreMode
    dry_run: bool
    tenants: list[str]
    tables: dict[str, int] = field(default_factory=dict)  # rows inserted per table
    counts_after: dict[str, int] = field(default_factory=dict)  # rows in scope after restore
    blobs_restored: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return True


def read_manifest(zf: zipfile.ZipFile) -> Manifest:
    try:
        raw = zf.read(MANIFEST_NAME).decode("utf-8")
    except KeyError as exc:
        raise ManifestError("archive has no manifest.json") from exc
    return Manifest.from_json(raw)


def _sha256_member(zf: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with zf.open(member) as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def check_member_hashes(zf: zipfile.ZipFile, manifest: Manifest) -> list[str]:
    """Return a list of problems (empty = every member matches the manifest)."""
    problems: list[str] = []
    names = set(zf.namelist())
    for member, expected in manifest.file_hashes().items():
        if member not in names:
            problems.append(f"missing member {member}")
            continue
        actual = _sha256_member(zf, member)
        if actual != expected:
            problems.append(
                f"hash mismatch {member}: expected {expected[:12]}…, got {actual[:12]}…"
            )
    if manifest.compute_total() != manifest.sha256_total:
        problems.append("sha256_total does not match the member hashes")
    return problems


def _jsonl_rows(zf: zipfile.ZipFile, member: str) -> Iterator[str]:
    with zf.open(member) as fh:
        for raw in fh:
            line = raw.decode("utf-8").rstrip("\n")
            if line:
                yield line


def _insert_ignore(conn: Connection, table: Table, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    if conn.dialect.name == "postgresql":
        stmt_pg = postgresql.insert(table).on_conflict_do_nothing()
        conn.execute(stmt_pg, rows)
    else:
        stmt_sq = sqlite.insert(table).on_conflict_do_nothing()
        conn.execute(stmt_sq, rows)


def _insert(conn: Connection, table: Table, rows: list[dict[str, Any]], ignore: bool) -> None:
    if not rows:
        return
    if ignore:
        _insert_ignore(conn, table, rows)
    else:
        conn.execute(table.insert(), rows)


def _count(conn: Connection, table: Table, tenant_id: str | None) -> int:
    stmt = select(func.count()).select_from(table)
    if tenant_id is not None and not is_global(table):
        stmt = stmt.where(tenant_filter(table, tenant_id))
    return int(conn.execute(stmt).scalar_one())


def _delete_tenant(conn: Connection, tenant_id: str) -> None:
    for table in reversed(export_tables()):
        if is_global(table):
            continue
        conn.execute(delete(table).where(tenant_filter(table, tenant_id)))


def _delete_everything(conn: Connection) -> None:
    for table in reversed(export_tables()):
        if is_global(table):
            continue
        conn.execute(delete(table))


def _reset_sequences(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return
    for table in export_tables():
        pk = list(table.primary_key.columns)
        if len(pk) == 1 and pk[0].autoincrement is True and pk[0].type.python_type is int:
            col = pk[0].name
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
                    f'COALESCE((SELECT MAX({col}) FROM "{table.name}"), 0) + 1, false)'
                )
            )


def _tenant_rows(zf: zipfile.ZipFile, manifest: Manifest) -> list[dict[str, Any]]:
    entry = next((t for t in manifest.tables if t.name == "tenant"), None)
    if entry is None:
        raise RestoreError("archive has no tenant table")
    tenant_table = Base.metadata.tables["tenant"]
    rows: list[dict[str, Any]] = []
    for line in _jsonl_rows(zf, entry.file):
        row, _ = decode_row(tenant_table, line)
        rows.append(row)
    return rows


def _existing_tenants(conn: Connection, ids: list[str], slugs: list[str]) -> list[tuple[str, str]]:
    tenant = Base.metadata.tables["tenant"]
    stmt = select(tenant.c.id, tenant.c.slug).where(tenant.c.id.in_(ids) | tenant.c.slug.in_(slugs))
    return [(str(r[0]), str(r[1])) for r in conn.execute(stmt).all()]


def _restore_blobs(
    zf: zipfile.ZipFile, manifest: Manifest, attachments: list[dict[str, Any]], storage_path: Path
) -> tuple[int, list[str]]:
    by_sha = {b.sha256: b for b in manifest.blobs}
    restored = 0
    warnings: list[str] = []
    for att in attachments:
        blob = by_sha.get(str(att["sha256"]))
        if blob is None:
            warnings.append(f"attachment {str(att['sha256'])[:12]}… not in archive")
            continue
        dest = storage_path / str(att["storage_key"])
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(blob.file) as src, dest.open("wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        restored += 1
    return restored, warnings


def restore_backup(
    zip_path: Path,
    engine: Engine,
    *,
    tenant_slug_override: str | None = None,
    mode: RestoreMode = "fail_if_exists",
    dry_run: bool = False,
    storage_path: Path | None = None,
    check_hashes: bool = True,
) -> RestoreResult:
    """Restore ``zip_path`` into ``engine``.

    * the database is migrated to head first (the manifest's schema revision
      must not be newer than the code);
    * all tables are inserted in foreign-key order inside one transaction;
    * ``mode``: ``fail_if_exists`` refuses when a tenant of the archive already
      exists, ``replace`` deletes that tenant's rows first, ``merge_new`` inserts
      only rows whose primary key is free;
    * row counts in scope are compared with the manifest afterwards (except in
      ``merge_new``) and a mismatch rolls everything back;
    * ``tenant_slug_override`` renames the (single) tenant of the archive — IDs
      are preserved, so this works on a database that does not contain the
      original tenant; a same-database clone needs ID remapping (not implemented);
    * ``dry_run`` performs everything and rolls back at the end.
    """
    if not zip_path.is_file():
        raise RestoreError(f"archive not found: {zip_path}")
    runner.upgrade(engine=engine)
    head = runner.head()
    result = RestoreResult(archive=zip_path, mode=mode, dry_run=dry_run, tenants=[])

    with zipfile.ZipFile(zip_path) as zf:
        manifest = read_manifest(zf)
        if check_hashes:
            problems = check_member_hashes(zf, manifest)
            if problems:
                raise RestoreError("archive integrity: " + "; ".join(problems))
        if manifest.schema_revision != head:
            result.warnings.append(
                f"archive schema revision {manifest.schema_revision} differs from head {head}; "
                "unknown columns are dropped, missing ones must have defaults"
            )
        tenant_rows = _tenant_rows(zf, manifest)
        if tenant_slug_override is not None:
            if len(tenant_rows) != 1:
                raise RestoreError("--as needs an archive with exactly one tenant")
            tenant_rows[0]["slug"] = tenant_slug_override
        tenant_ids = [str(r["id"]) for r in tenant_rows]
        tenant_slugs = [str(r["slug"]) for r in tenant_rows]
        result.tenants = tenant_slugs
        by_name = {t.name: t for t in manifest.tables}
        ignore_conflicts = mode == "merge_new"
        scope_all = manifest.tenant is None  # counts and replace act on the whole database

        conn = engine.connect()
        trans = conn.begin()
        try:
            existing = _existing_tenants(conn, tenant_ids, tenant_slugs)
            if existing and mode == "fail_if_exists":
                raise RestoreError(
                    "tenant(s) already exist: "
                    + ", ".join(f"{slug} ({tid[:8]}…)" for tid, slug in existing)
                    + " — use --mode replace or --as <new-slug>"
                )
            if mode == "replace":
                if scope_all:
                    # An all-tenant archive replaces the whole database (minus master data).
                    _delete_everything(conn)
                else:
                    for tid, _slug in existing:
                        _delete_tenant(conn, tid)
                # a slug clash with a different id is still a clash
                still = _existing_tenants(conn, tenant_ids, tenant_slugs)
                if still:
                    raise RestoreError(
                        "slug already used by another tenant: "
                        + ", ".join(slug for _, slug in still)
                    )

            attachments: list[dict[str, Any]] = []
            for table in export_tables():
                entry = by_name.get(table.name)
                if entry is None:
                    result.warnings.append(f"table {table.name} not in archive (skipped)")
                    continue
                if table.name == "tenant":
                    rows_iter: Iterator[dict[str, Any]] = iter(tenant_rows)
                else:
                    rows_iter = _decoded(zf, table, entry.file, result.warnings)
                inserted = 0
                batch: list[dict[str, Any]] = []
                for row in rows_iter:
                    if table.name == "attachment":
                        attachments.append(row)
                    batch.append(row)
                    if len(batch) >= _BATCH:
                        _insert(conn, table, batch, ignore=ignore_conflicts or is_global(table))
                        inserted += len(batch)
                        batch = []
                if batch:
                    _insert(conn, table, batch, ignore=ignore_conflicts or is_global(table))
                    inserted += len(batch)
                result.tables[table.name] = inserted

            _reset_sequences(conn)

            # Count check: every archived table must now hold as many rows in scope.
            mismatches: list[str] = []
            for table in export_tables():
                entry = by_name.get(table.name)
                if entry is None or is_global(table):
                    continue
                if scope_all:
                    total = _count(conn, table, None)
                else:
                    total = sum(_count(conn, table, tid) for tid in tenant_ids)
                result.counts_after[table.name] = total
                if not ignore_conflicts and total != entry.rows:
                    mismatches.append(f"{table.name}: archive {entry.rows}, database {total}")
            if mismatches:
                raise RestoreError("row counts differ after restore: " + "; ".join(mismatches))

            if dry_run:
                trans.rollback()
            else:
                trans.commit()
        except Exception:
            if trans.is_active:
                trans.rollback()
            raise
        finally:
            conn.close()

        if not dry_run and storage_path is not None and attachments:
            restored, blob_warnings = _restore_blobs(zf, manifest, attachments, storage_path)
            result.blobs_restored = restored
            result.warnings.extend(blob_warnings)
        elif attachments and storage_path is None and not dry_run:
            result.warnings.append("attachments not restored: no storage path")

    return result


def _decoded(
    zf: zipfile.ZipFile, table: Table, member: str, warnings: list[str]
) -> Iterator[dict[str, Any]]:
    reported: set[str] = set()
    for line in _jsonl_rows(zf, member):
        row, unknown = decode_row(table, line)
        for col in unknown:
            if col not in reported:
                reported.add(col)
                warnings.append(f"{table.name}.{col} is not a column any more — value dropped")
        yield row


__all__ = [
    "RestoreError",
    "RestoreMode",
    "RestoreResult",
    "check_member_hashes",
    "read_manifest",
    "restore_backup",
]
