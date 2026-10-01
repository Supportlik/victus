"""T-OPS-220 … T-OPS-229: `victus backup …` commands and their exit codes.

Exit codes: 0 ok, 1 mismatch, 2 input.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from tests.cli_support import CliEnv, cli, configure_cli_env
from victus.backup import schedule as schedule_mod
from victus.backup.export import list_archives
from victus.backup.retention import FAILED_SUFFIX
from victus.backup.schedule import ALIVE_MARKER, JobOutcome
from victus.backup.verify import VerifyResult
from victus.cli import backup_cmd
from victus.cli.main import app
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine

from .conftest import Seeded

pytestmark = pytest.mark.service


@pytest.fixture
def env(seeded: Seeded, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CliEnv:
    return configure_cli_env(
        monkeypatch,
        tmp_path,
        db_path=seeded.db_path,
        storage=seeded.storage,
        backups=seeded.backups,
        migrate=False,
    )


def _create(*args: str) -> Path:
    result = cli.invoke(app, ["backup", "create", *args])
    assert result.exit_code == 0, result.output
    return Path(result.stdout.split("  (")[0])


def _stamp(dir_: Path, ts: datetime, scope: str = "all") -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"victus-{scope}-{ts.strftime('%Y%m%dT%H%M%SZ')}.zip"
    p.write_bytes(b"x" * 10)
    return p


def _point_at_fresh_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'restored.db').as_posix()}"
    monkeypatch.setenv("VICTUS_DATABASE__URL", url)
    monkeypatch.setenv("VICTUS_STORAGE__PATH", str(tmp_path / "restored-blobs"))
    return url


def _count(url: str, table: str) -> int:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(orm.Base.metadata.tables[table])
                ).scalar_one()
            )
    finally:
        engine.dispose()


def test_create_tenant_and_all(env: CliEnv) -> None:
    """T-OPS-220: `create` writes a tenant or an all-tenant archive and prints its size and
    counts."""
    result = cli.invoke(app, ["backup", "create", "--tenant", "alice"])
    assert result.exit_code == 0, result.output
    assert "victus-alice-" in result.stdout
    assert "tables, 1 blobs)" in result.stdout
    assert result.stderr == ""

    target = env.backups / "elsewhere"
    everything = _create("--all", "--no-snapshot", "--target", str(target))
    assert everything.parent == target and everything.name.startswith("victus-all-")
    with zipfile.ZipFile(everything) as zf:
        assert "snapshot/victus.db" not in zf.namelist()


def test_create_input_errors_exit_2(env: CliEnv) -> None:
    """T-OPS-221: `--tenant` with `--all`, or an unknown tenant, exits 2 and writes nothing."""
    both = cli.invoke(app, ["backup", "create", "--tenant", "alice", "--all"])
    assert both.exit_code == 2
    assert "--tenant and --all exclude each other" in both.stderr
    unknown = cli.invoke(app, ["backup", "create", "--tenant", "nobody"])
    assert unknown.exit_code == 2
    assert "tenant 'nobody' not found" in unknown.stderr
    assert list_archives(env.backups) == []


def test_create_warns_about_a_missing_attachment(env: CliEnv) -> None:
    """T-OPS-222: an attachment missing on disk is a warning on stderr, not a failure."""
    for blob in [p for p in env.storage.rglob("*") if p.is_file()]:
        blob.unlink()
    result = cli.invoke(app, ["backup", "create", "--tenant", "alice"])
    assert result.exit_code == 0, result.output
    assert "0 blobs)" in result.stdout
    assert "  warning: attachment " in result.stderr and "missing on disk" in result.stderr


def test_verify_exit_codes(env: CliEnv) -> None:
    """T-OPS-223: `verify` exits 0 on a sound archive, 1 on a tampered one, 2 without an archive."""
    none_yet = cli.invoke(app, ["backup", "verify", "--latest"])
    assert none_yet.exit_code == 2
    assert f"no archives in {env.backups}" in none_yet.stderr
    no_arg = cli.invoke(app, ["backup", "verify"])
    assert no_arg.exit_code == 2
    assert "give an archive path or --latest" in no_arg.stderr

    archive = _create("--tenant", "alice")
    ok = cli.invoke(app, ["backup", "verify", "--latest"])
    assert ok.exit_code == 0, ok.output
    assert f"{archive.name}: OK (scope alice" in ok.stdout
    assert "tables," in ok.stdout and "rows, views ok" in ok.stdout
    # A bare file name resolves against the backup directory.
    by_name = cli.invoke(app, ["backup", "verify", archive.name])
    assert by_name.exit_code == 0

    missing = cli.invoke(app, ["backup", "verify", "victus-alice-20200101T000000Z.zip"])
    assert missing.exit_code == 2
    assert "archive not found" in missing.stderr

    tampered = archive.with_name(archive.name.replace("alice", "bob"))
    with zipfile.ZipFile(archive) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "data/weight_entry.jsonl":
                data = data.replace(b"91.2", b"99.9")
            dst.writestr(info, data)
    bad = cli.invoke(app, ["backup", "verify", str(tampered)])
    assert bad.exit_code == 1
    assert "FAILED" in bad.stdout and "hash mismatch data/weight_entry.jsonl" in bad.stdout


def test_restore_into_fresh_database(
    env: CliEnv, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T-OPS-224: `restore --yes` restores rows and blobs; `--dry-run` changes nothing."""
    archive = _create("--tenant", "alice")
    url = _point_at_fresh_db(monkeypatch, tmp_path)

    dry = cli.invoke(app, ["backup", "restore", str(archive), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert dry.stdout.startswith(f"would restore tenant(s) alice from {archive.name}")
    assert "blobs restored" not in dry.stdout
    assert _count(url, "tenant") == 0

    done = cli.invoke(app, ["backup", "restore", archive.name, "--as", "carol", "-y"])
    assert done.exit_code == 0, done.output
    lines = done.stdout.splitlines()
    assert lines[0] == f"restored tenant(s) carol from {archive.name}"
    assert any(line.split() == ["line_item", "2"] for line in lines)
    assert not any(line.split()[-1] == "0" for line in lines[1:])  # empty tables are not listed
    assert "  blobs restored: 1" in lines
    assert _count(url, "line_item") == 2


def test_restore_refusals_exit_1_or_2(env: CliEnv) -> None:
    """T-OPS-225: a bad mode exits 2; an existing tenant or a broken archive exits 1."""
    archive = _create("--tenant", "alice")
    bad_mode = cli.invoke(app, ["backup", "restore", str(archive), "--mode", "overwrite"])
    assert bad_mode.exit_code == 2
    assert "mode must be fail_if_exists, replace or merge_new" in bad_mode.stderr

    exists = cli.invoke(app, ["backup", "restore", str(archive), "--yes"])
    assert exists.exit_code == 1
    assert "restore failed: tenant(s) already exist: alice" in exists.stderr

    no_manifest = env.backups / "victus-all-20200101T000000Z.zip"
    with zipfile.ZipFile(no_manifest, "w") as zf:
        zf.writestr("data/tenant.jsonl", "")
    broken = cli.invoke(app, ["backup", "restore", str(no_manifest), "--yes"])
    assert broken.exit_code == 1
    assert "restore failed: archive has no manifest.json" in broken.stderr


def test_restore_asks_for_confirmation_and_reports_warnings(
    env: CliEnv, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T-OPS-226: without --yes a "no" aborts (exit 1); restore warnings go to stderr."""
    for blob in [p for p in env.storage.rglob("*") if p.is_file()]:
        blob.unlink()
    archive = _create("--tenant", "alice")  # the attachment row has no blob in the archive
    url = _point_at_fresh_db(monkeypatch, tmp_path)

    declined = cli.invoke(app, ["backup", "restore", str(archive)], input="n\n")
    assert declined.exit_code == 1
    assert f"Restore {archive.name} into {url} (mode fail_if_exists)?" in declined.output
    assert "Aborted" in declined.output

    accepted = cli.invoke(app, ["backup", "restore", str(archive)], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert "warning: attachment " in accepted.stderr and "not in archive" in accepted.stderr
    assert "blobs restored" not in accepted.stdout


def test_list_archives_newest_first(env: CliEnv) -> None:
    """T-OPS-227: `list` prints size and name, newest first; an empty directory says so."""
    empty = cli.invoke(app, ["backup", "list"])
    assert empty.exit_code == 0
    assert empty.stdout.strip() == f"no archives in {env.backups}"
    old = _stamp(env.backups, datetime(2026, 1, 1, 3, tzinfo=UTC))
    new = _stamp(env.backups, datetime(2026, 2, 1, 3, tzinfo=UTC))
    (env.backups / "notes.txt").write_text("not an archive", encoding="utf-8")
    listed = cli.invoke(app, ["backup", "list", "--target", str(env.backups)])
    assert listed.exit_code == 0
    assert [line.split() for line in listed.stdout.strip().splitlines()] == [
        ["10", new.name],
        ["10", old.name],
    ]


def test_prune_applies_retention(env: CliEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-OPS-228: `prune --dry-run` only reports; `prune` deletes outside the retention windows."""
    monkeypatch.setenv("VICTUS_BACKUP__RETENTION__DAILY", "2")
    monkeypatch.setenv("VICTUS_BACKUP__RETENTION__WEEKLY", "0")
    monkeypatch.setenv("VICTUS_BACKUP__RETENTION__MONTHLY", "0")
    now = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    paths = [_stamp(env.backups, now - timedelta(days=d)) for d in range(4)]

    dry = cli.invoke(app, ["backup", "prune", "--dry-run"])
    assert dry.exit_code == 0
    assert dry.stdout.splitlines()[-1] == "kept 2, would delete 2"
    assert f"would delete  {paths[3].name}" in dry.stdout
    assert all(p.exists() for p in paths)

    real = cli.invoke(app, ["backup", "prune"])
    assert real.exit_code == 0
    assert real.stdout.splitlines()[-1] == "kept 2, deleted 2"
    assert f"deleting  {paths[2].name}" in real.stdout
    assert [p.exists() for p in paths] == [True, True, False, False]


def test_schedule_once_and_input_errors(env: CliEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-OPS-229: `schedule --once` runs one verified cycle; flag or cron errors exit 2."""
    neither = cli.invoke(app, ["backup", "schedule"])
    assert neither.exit_code == 2
    assert "choose --daemon or --once" in neither.stderr
    both = cli.invoke(app, ["backup", "schedule", "--daemon", "--once"])
    assert both.exit_code == 2

    once = cli.invoke(app, ["backup", "schedule", "--once"])
    assert once.exit_code == 0, once.output
    assert once.stdout.startswith("ok victus-all-") and once.stdout.strip().endswith(" verified")
    assert (env.backups / ALIVE_MARKER).exists()

    monkeypatch.setenv("VICTUS_BACKUP__CRON", "every night")
    bad_cron = cli.invoke(app, ["backup", "schedule", "--once"])
    assert bad_cron.exit_code == 2
    assert "cron expression needs 5 fields" in bad_cron.stderr


def test_schedule_once_failed_verification_exits_1(
    env: CliEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-OPS-230: a cycle whose verification fails prints FAILED, marks the archive, exits 1."""

    def failing(path: Path) -> VerifyResult:
        return VerifyResult(archive=path, ok=False, problems=["row counts differ"])

    monkeypatch.setattr(schedule_mod, "verify_backup", failing)
    result = cli.invoke(app, ["backup", "schedule", "--once"])
    assert result.exit_code == 1
    assert result.stdout.startswith("FAILED victus-all-")
    assert "verification failed: row counts differ" in result.stdout
    [archive] = list_archives(env.backups)
    assert archive.with_name(archive.name + FAILED_SUFFIX).exists()


def test_schedule_daemon_reports_every_outcome(
    env: CliEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-OPS-231: `schedule --daemon` passes cron and retention and prints one line per cycle."""
    seen: dict[str, Any] = {}
    archive = env.backups / "victus-all-20260105T030000Z.zip"

    def fake_run_scheduled(engine: Any, **kw: Any) -> list[JobOutcome]:
        seen.update(kw)
        outcomes = [
            JobOutcome(job_id="j1", archive=archive, verified=True, deleted=[Path("a"), Path("b")]),
            JobOutcome(job_id="j2", archive=None, verified=False, error="OSError: disk full"),
        ]
        for o in outcomes:
            kw["on_outcome"](o)
        return outcomes

    monkeypatch.setattr(backup_cmd, "run_scheduled", fake_run_scheduled)
    result = cli.invoke(app, ["backup", "schedule", "--daemon"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        f"ok {archive.name} verified deleted 2",
        "FAILED - OSError: disk full",
    ]
    assert seen["once"] is False
    assert seen["cron"] == "0 3 * * *"
    assert seen["retention"] == (7, 8, 12)
    assert seen["target_dir"] == env.backups
