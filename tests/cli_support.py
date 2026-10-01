"""Helpers for CLI tests: a plain CliRunner and an isolated server configuration.

CLI commands load their own configuration (``victus.yaml`` / ``VICTUS_*``) and open their
own engine, so the tests point the environment at a file SQLite database under
``tmp_path`` and at a ``victus.yaml`` that does not exist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from victus.infrastructure.db.engine import make_engine
from victus.infrastructure.migrations import runner as migrations

# Plain, wide output: no Rich colours, no 80-column wrapping.
cli = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"})


@dataclass
class CliEnv:
    db_url: str
    db_path: Path
    storage: Path
    backups: Path


def configure_cli_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    db_path: Path | None = None,
    storage: Path | None = None,
    backups: Path | None = None,
    migrate: bool = True,
) -> CliEnv:
    """Point every ``VICTUS_*`` setting a CLI command reads at ``tmp_path``."""
    for key in list(os.environ):
        if key.startswith("VICTUS_"):
            monkeypatch.delenv(key, raising=False)
    db = db_path or tmp_path / "cli.db"
    blobs = storage or tmp_path / "blobs"
    target = backups or tmp_path / "backups"
    url = f"sqlite:///{db.as_posix()}"
    monkeypatch.setenv("VICTUS_CONFIG", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("VICTUS_DATABASE__URL", url)
    monkeypatch.setenv("VICTUS_STORAGE__PATH", str(blobs))
    monkeypatch.setenv("VICTUS_BACKUP__PATH", str(target))
    monkeypatch.setenv("VICTUS_WORKER_HEARTBEAT", str(tmp_path / "worker.alive"))
    if migrate:
        engine = make_engine(url)
        try:
            migrations.upgrade(engine=engine)
        finally:
            engine.dispose()
    return CliEnv(db_url=url, db_path=db, storage=blobs, backups=target)
