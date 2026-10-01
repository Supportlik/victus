"""T-OPS-232…235: what ``verify_backup`` reports for archives that are not what they claim."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine

from victus.backup import verify as verify_mod
from victus.backup.export import create_backup
from victus.backup.restore import RestoreError
from victus.backup.verify import verify_backup
from victus.infrastructure.migrations import runner

from .conftest import Seeded

pytestmark = pytest.mark.service


def test_t_ops_232_missing_unreadable_and_manifestless_archives(tmp_path: Path) -> None:
    """T-OPS-232: a missing file, a file that is no zip and a zip without a manifest each
    fail with what is wrong, and the summary lists it."""
    missing = verify_backup(tmp_path / "nope.zip")
    assert not missing.ok and missing.problems == ["file not found"]

    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"this is not a zip")
    assert not verify_backup(junk).ok

    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "no manifest here")
    result = verify_backup(empty)
    assert not result.ok and result.problems
    assert "FAILED" in result.summary() and "\n  - " in result.summary()


def test_t_ops_233_a_corrupt_member_is_named(seeded: Seeded, tmp_path: Path) -> None:
    """T-OPS-233: a member whose bytes no longer match its CRC is reported by name before
    anything is restored."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)
    stored = tmp_path / "stored.zip"
    with (
        zipfile.ZipFile(archive.path) as src,
        zipfile.ZipFile(stored, "w", zipfile.ZIP_STORED) as dst,
    ):
        for info in src.infolist():
            dst.writestr(info.filename, src.read(info.filename))
    raw = bytearray(stored.read_bytes())
    marker = raw.find(b'"base_amount"')
    assert marker > 0
    raw[marker + 2] ^= 0x01  # one flipped bit inside a stored member
    stored.write_bytes(bytes(raw))

    result = verify_backup(stored)
    assert not result.ok
    assert any(p.startswith("corrupt zip member") for p in result.problems)


@pytest.mark.parametrize(
    ("failure", "fragment"),
    [
        (RestoreError("tenant exists"), "tenant exists"),
        (RuntimeError("disk"), "RuntimeError: disk"),
    ],
)
def test_t_ops_234_a_restore_that_fails_is_a_problem_not_a_crash(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch, failure: Exception, fragment: str
) -> None:
    """T-OPS-234: a restore error and any other error during the trial restore end up in
    ``problems``."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)

    def fail(*_a: Any, **_k: Any) -> Any:
        raise failure

    monkeypatch.setattr(verify_mod, "restore_backup", fail)
    result = verify_backup(archive.path)
    assert not result.ok and any(fragment in p for p in result.problems)


def test_t_ops_235_foreign_key_violations_are_counted(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-OPS-235: rows that point at nothing after the trial restore fail the check."""
    archive = create_backup(seeded.engine, seeded.backups, "alice", storage_path=seeded.storage)

    def orphaned(_zip: Path, engine: Engine, **_k: Any) -> Any:
        runner.upgrade(engine=engine)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.exec_driver_sql(
                "INSERT INTO user (id, tenant_id, display_name, role, created_at) "
                "VALUES ('u1', 'no-such-tenant', 'Ghost', 'member', '2026-01-01 00:00:00')"
            )
            conn.commit()
        return SimpleNamespace(counts_after={"user": 1})

    monkeypatch.setattr(verify_mod, "restore_backup", orphaned)
    result = verify_backup(archive.path)
    assert not result.ok
    assert "1 foreign key violation(s)" in result.problems
