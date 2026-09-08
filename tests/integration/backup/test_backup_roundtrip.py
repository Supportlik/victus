"""T-OPS-001 … T-OPS-004, T-OPS-011 … T-OPS-013: backup create, verify, restore."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import Engine, text

from victus.backup.export import create_backup, list_archives
from victus.backup.restore import RestoreError, restore_backup
from victus.backup.scoping import check_coverage
from victus.backup.verify import verify_backup
from victus.infrastructure.migrations import runner

from .conftest import Seeded

pytestmark = pytest.mark.service

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "schemas" / "backup-manifest.schema.json").read_text(
        encoding="utf-8"
    )
)


def _rows(zf: zipfile.ZipFile, table: str) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in zf.read(f"data/{table}.jsonl").decode().splitlines() if line
    ]


def _day_macros(engine: Engine, tenant_id: str) -> list[tuple[object, ...]]:
    with engine.connect() as c:
        return [
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT date, kcal, protein, carbs, fat, fiber, salt FROM day_macros "
                    "WHERE tenant_id = :t ORDER BY date"
                ),
                {"t": tenant_id},
            ).all()
        ]


def test_every_table_is_scoped_or_global() -> None:
    """Every table can be attributed to a tenant (or is global master data)."""
    assert check_coverage() == []


def test_create_tenant_archive_contains_only_that_tenant(seeded: Seeded) -> None:
    """T-OPS-001: ZIP with manifest, one JSONL per table, blob by hash; counts equal DB counts."""
    archive = create_backup(
        seeded.engine,
        seeded.backups,
        "alice",
        storage_path=seeded.storage,
        now=datetime(2026, 9, 8, 3, 0, tzinfo=UTC),
    )
    assert archive.path.name == "victus-alice-20260908T030000Z.zip"
    assert archive.warnings == []
    m = archive.manifest
    jsonschema.validate(m.to_dict(), SCHEMA)
    assert m.tenant is not None and m.tenant.slug == "alice"
    assert m.includes_sqlite_snapshot and m.sqlite_snapshot is not None
    with zipfile.ZipFile(archive.path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names and "snapshot/victus.db" in names
        tenants = _rows(zf, "tenant")
        assert [t["slug"] for t in tenants] == ["alice"]
        users = _rows(zf, "user")
        assert {u["email"] for u in users} == {"alice@example.com"}
        assert all(r["tenant_id"] == seeded.alice.tenant_id for r in _rows(zf, "consumable"))
        assert len(_rows(zf, "line_item")) == 2
        assert len(_rows(zf, "unit")) > 20  # global master data always complete
        assert len(_rows(zf, "attachment")) == 1
        assert len(m.blobs) == 1 and f"blobs/{m.blobs[0].sha256}" in names
        pk = _rows(zf, "passkey_credential")[0]
        assert isinstance(pk["public_key"], str)  # base64
    by_name = {t.name: t.rows for t in m.tables}
    assert by_name["day_log"] == 1 and by_name["meal"] == 1 and by_name["weight_entry"] == 1
    assert by_name["tenant"] == 1 and by_name["portion"] == 1


def test_create_all_tenants(seeded: Seeded) -> None:
    archive = create_backup(
        seeded.engine,
        seeded.backups,
        None,
        storage_path=seeded.storage,
        include_sqlite_snapshot=False,
    )
    assert archive.manifest.tenant is None
    assert archive.manifest.scope_label == "all"
    assert not archive.manifest.includes_sqlite_snapshot
    by_name = {t.name: t.rows for t in archive.manifest.tables}
    assert by_name["tenant"] == 2 and by_name["line_item"] == 4
    assert list_archives(seeded.backups)[0] == archive.path


def test_verify_ok_and_tampered(seeded: Seeded) -> None:
    """T-OPS-002: verify exits ok; a tampered JSONL is reported with the table name."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    result = verify_backup(archive.path)
    assert result.ok, result.problems
    assert result.tables["line_item"] == 2
    assert result.views["day_macros"] == 1

    tampered = archive.path.with_name("victus-alice-20250101T000000Z.zip")
    with zipfile.ZipFile(archive.path) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "data/line_item.jsonl":
                data = data.replace(b'"base_amount": 400.0', b'"base_amount": 401.0')
                assert b"401.0" in data
            dst.writestr(info, data)
    bad = verify_backup(tampered)
    assert not bad.ok
    assert any("line_item" in p for p in bad.problems)


def test_restore_round_trip_into_fresh_db(seeded: Seeded, fresh_engine: Engine) -> None:
    """T-OPS-003: counts and computed nutrients identical after restore; blobs back on disk."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    before = _day_macros(seeded.engine, seeded.alice.tenant_id)
    new_storage = seeded.backups / "restored-blobs"
    result = restore_backup(archive.path, fresh_engine, storage_path=new_storage)
    assert result.tenants == ["alice"]
    assert result.blobs_restored == 1
    assert result.warnings == []
    for entry in archive.manifest.tables:
        if entry.name != "unit":
            assert result.counts_after[entry.name] == entry.rows, entry.name
    assert _day_macros(fresh_engine, seeded.alice.tenant_id) == before
    assert runner.is_up_to_date(engine=fresh_engine)
    blob = archive.manifest.blobs[0]
    restored_files = list(new_storage.rglob("*"))
    assert any(p.is_file() and p.name == blob.sha256 for p in restored_files)
    with fresh_engine.connect() as c:
        pk = c.execute(text("SELECT public_key, sign_count FROM passkey_credential")).one()
        assert bytes(pk[0]).startswith(b"\x01\x02\x03") and pk[1] == 3
        assert c.execute(text("PRAGMA foreign_key_check")).all() == []


def test_restore_refuses_existing_tenant_then_replaces(seeded: Seeded) -> None:
    """T-OPS-012: fail_if_exists refuses; replace swaps the tenant's rows and leaves bob alone."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    with pytest.raises(RestoreError, match="already exist"):
        restore_backup(archive.path, seeded.engine, storage_path=seeded.storage)
    # damage alice's data, then restore with replace
    with seeded.engine.begin() as c:
        c.execute(text("DELETE FROM line_item"))
    assert _day_macros(seeded.engine, seeded.alice.tenant_id)[0][1] is None
    result = restore_backup(
        archive.path, seeded.engine, mode="replace", storage_path=seeded.storage
    )
    assert result.counts_after["line_item"] == 2
    assert _day_macros(seeded.engine, seeded.alice.tenant_id)[0][1] == 475  # 400 g skyr + 60 g oats
    with seeded.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM tenant")).scalar_one() == 2
        # bob lost his line items through our DELETE above, not through the restore
        assert c.execute(text("SELECT count(*) FROM day_log")).scalar_one() == 2


def test_restore_into_new_slug(seeded: Seeded, fresh_engine: Engine) -> None:
    """T-OPS-004: --as renames the tenant; counts identical."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    result = restore_backup(archive.path, fresh_engine, tenant_slug_override="alice-test")
    assert result.tenants == ["alice-test"]
    with fresh_engine.connect() as c:
        assert c.execute(text("SELECT slug FROM tenant")).scalar_one() == "alice-test"
        assert c.execute(text("SELECT count(*) FROM line_item")).scalar_one() == 2


def test_dry_run_leaves_database_empty(seeded: Seeded, fresh_engine: Engine) -> None:
    """T-OPS-013: dry run performs the full import and rolls back."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    result = restore_backup(archive.path, fresh_engine, dry_run=True)
    assert result.dry_run and result.counts_after["line_item"] == 2
    with fresh_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM tenant")).scalar_one() == 0


def test_restore_all_archive_merge_new(seeded: Seeded, fresh_engine: Engine) -> None:
    """T-OPS-011: an all-tenant archive restores both tenants; merge_new is idempotent."""
    archive = create_backup(seeded.engine, seeded.backups, None, storage_path=seeded.storage)
    first = restore_backup(archive.path, fresh_engine)
    assert sorted(first.tenants) == ["alice", "bob"]
    second = restore_backup(archive.path, fresh_engine, mode="merge_new")
    assert sorted(second.tenants) == ["alice", "bob"]
    with fresh_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM line_item")).scalar_one() == 4
