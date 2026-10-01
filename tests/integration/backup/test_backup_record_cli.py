"""T-OPS-110…113: `victus backup record` and `backup create` leave a `backup_job` row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from victus.application.use_cases.system import Health
from victus.cli.main import app
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_session_factory

from .conftest import Seeded

pytestmark = pytest.mark.service

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})


@pytest.fixture
def cli_env(seeded: Seeded, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Seeded:
    monkeypatch.setenv("VICTUS_CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("VICTUS_DATABASE__URL", f"sqlite:///{seeded.db_path.as_posix()}")
    monkeypatch.setenv("VICTUS_STORAGE__PATH", str(seeded.storage))
    monkeypatch.setenv("VICTUS_BACKUP__PATH", str(seeded.backups))
    return seeded


def _jobs(seeded: Seeded) -> list[orm.BackupJob]:
    with Session(seeded.engine) as s:
        return list(s.scalars(select(orm.BackupJob).order_by(orm.BackupJob.started_at)).all())


def _backup_check(seeded: Seeded) -> str:
    view = Health(seeded.engine, make_session_factory(seeded.engine), seeded.storage).execute()
    return view.checks["backup"]


def test_t_ops_110_record_a_host_backup(cli_env: Seeded) -> None:
    """T-OPS-110: a host backup reports in with path and size; /health turns `ok`."""
    assert _backup_check(cli_env) == "degraded"
    r = runner.invoke(
        app, ["backup", "record", "--path", "/mnt/backup/victus-data.tar.gpg", "--size", "4096"]
    )
    assert r.exit_code == 0, r.output
    assert "recorded finished backup" in r.output and "4,096 bytes" in r.output
    (job,) = _jobs(cli_env)
    assert job.status == "finished" and job.path == "/mnt/backup/victus-data.tar.gpg"
    assert job.size == 4096 and job.tenant_id is None and job.verified is False
    assert job.finished_at is not None
    assert datetime.now(UTC) - job.finished_at < timedelta(minutes=1)
    assert _backup_check(cli_env) == "ok"


def test_t_ops_111_record_options(cli_env: Seeded, tmp_path: Path) -> None:
    """T-OPS-111: size read from a visible file, `--at` with offset, `--tenant`, and a
    failure recorded with `--error` that leaves /health degraded."""
    archive = tmp_path / "host.tar"
    archive.write_bytes(b"x" * 321)
    at = (datetime.now(UTC) - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = runner.invoke(
        app, ["backup", "record", "--path", str(archive), "--at", at, "--tenant", "alice"]
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        app, ["backup", "record", "--path", "/mnt/backup/x.tar", "--error", "tar: no space left"]
    )
    assert r.exit_code == 0, r.output
    assert "recorded failed backup" in r.output and "size unknown" in r.output
    host, failed = _jobs(cli_env)
    assert host.size == 321 and host.tenant_id == cli_env.alice.tenant_id
    assert host.finished_at is not None
    assert host.finished_at.strftime("%Y-%m-%dT%H:%M:%SZ") == at
    assert failed.status == "failed" and failed.error == "tar: no space left"
    assert _backup_check(cli_env) == "degraded"  # 40 h old success, newer failure


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--at", "2026-09-15T03:00:00"], "offset"),
        (["--at", "yesterday"], "ISO 8601"),
        (["--at", "2999-01-01T00:00:00Z"], "future"),
        (["--tenant", "carol"], "carol"),
        (["--size", "-5"], "-5"),
    ],
)
def test_t_ops_112_record_refuses_bad_input(cli_env: Seeded, args: list[str], message: str) -> None:
    """T-OPS-112: a time without offset, garbage, a future time, an unknown tenant or a
    negative size exit 2 and record nothing."""
    r = runner.invoke(app, ["backup", "record", "--path", "/mnt/backup/x.tar", *args])
    assert r.exit_code == 2, r.output
    assert message in r.output
    assert _jobs(cli_env) == []


def test_t_ops_112_record_needs_a_path(cli_env: Seeded) -> None:
    """T-OPS-112: `--path` is required."""
    r = runner.invoke(app, ["backup", "record"])
    assert r.exit_code == 2
    assert _jobs(cli_env) == []


def test_t_ops_113_create_records_a_job(cli_env: Seeded) -> None:
    """T-OPS-113: `backup create` by hand is recorded like a scheduled run, so /health
    knows about it; a tenant archive carries the tenant."""
    r = runner.invoke(app, ["backup", "create", "--all", "--no-snapshot"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["backup", "create", "--tenant", "bob", "--no-snapshot"])
    assert r.exit_code == 0, r.output
    everyone, bob = _jobs(cli_env)
    assert everyone.status == "finished" and everyone.tenant_id is None
    assert everyone.path is not None and Path(everyone.path).is_file()
    assert everyone.size == Path(everyone.path).stat().st_size
    assert bob.tenant_id == cli_env.bob.tenant_id
    assert _backup_check(cli_env) == "ok"
