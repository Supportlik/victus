"""T-OPS-210 … T-OPS-219: process commands (serve, worker, mcp, migrate) and the agent group."""

from __future__ import annotations

import runpy
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import typer
from sqlalchemy import select

from tests.cli_support import CliEnv, cli, configure_cli_env
from victus import __version__
from victus.agent.worker import Worker
from victus.cli import main as cli_main
from victus.cli.main import NOT_IMPLEMENTED_EXIT, _planned, app
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine, make_session_factory

pytestmark = pytest.mark.service


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CliEnv:
    cfg = configure_cli_env(monkeypatch, tmp_path)
    assert cli.invoke(app, ["tenant", "create", "alice"]).exit_code == 0
    return cfg


def _session(env: CliEnv) -> Any:
    engine = make_engine(env.db_url)
    return engine, make_session_factory(engine)()


def _runs(env: CliEnv) -> list[orm.AgentRun]:
    engine, s = _session(env)
    try:
        return list(s.scalars(select(orm.AgentRun).order_by(orm.AgentRun.created_at)))
    finally:
        s.close()
        engine.dispose()


# ── root and process commands ────────────────────────────────────────────────


def test_version_command_and_no_args_help() -> None:
    """T-OPS-210: `victus version` prints the version; no arguments shows help (exit 2)."""
    result = cli.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"victus {__version__}"
    bare = cli.invoke(app, [])
    assert bare.exit_code == 2
    assert "Usage" in bare.output
    for group in ("backup", "token", "tenant", "user", "passkey", "agent"):
        assert cli.invoke(app, [group]).exit_code == 2, group


def test_planned_command_exits_3_and_names_the_stage(capsys: pytest.CaptureFixture[str]) -> None:
    """T-OPS-211: a placeholder command exits with code 3 and names the stage that delivers it."""
    placeholder = typer.Typer()

    @placeholder.command()
    def later() -> None:
        _planned("Stage 9", "victus later")

    result = cli.invoke(placeholder, [])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT == 3
    assert "'victus later' is planned for Stage 9 and not implemented yet." in result.output


def test_serve_migrates_then_runs_uvicorn(env: CliEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-OPS-212: `serve` migrates first (unless --no-migrate) and trusts forwarded headers."""
    import uvicorn

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: calls.append({"target": target, **kw}))

    result = cli.invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert "migrations: up to date (" in result.stderr
    assert calls == [
        {
            "target": "victus.api.app:create_app",
            "factory": True,
            "host": "0.0.0.0",
            "port": 9000,
            "reload": False,
            "proxy_headers": True,
            "forwarded_allow_ips": "*",
        }
    ]

    skipped = cli.invoke(app, ["serve", "--no-migrate", "--reload"])
    assert skipped.exit_code == 0
    assert "migrations" not in skipped.output
    assert calls[-1]["reload"] is True and calls[-1]["port"] == 8000


def test_migrate_upgrades_an_empty_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T-OPS-213: `migrate` brings an empty database to head and reports the revision."""
    env = configure_cli_env(monkeypatch, tmp_path, migrate=False)
    result = cli.invoke(app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert result.stderr.startswith("migrations: up to date (")
    assert "None" not in result.stderr
    assert env.db_path.is_file()


def test_worker_once_and_forever(env: CliEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-OPS-214: `worker --once` processes the queue and reports; without it the loop runs."""
    once = cli.invoke(app, ["worker", "--once"])
    assert once.exit_code == 0, once.output
    assert "processed 0 run(s)" in once.stderr

    started: list[Worker] = []
    monkeypatch.setattr(Worker, "run_forever", lambda self: started.append(self))
    forever = cli.invoke(app, ["worker"])
    assert forever.exit_code == 0
    assert len(started) == 1 and started[0].transcription is None


def test_mcp_serves_stdio_for_the_tenant(env: CliEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-OPS-215: `mcp --tenant` hands the tenant slug and the configuration to the stdio server."""
    import victus.mcp.server as mcp_server

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mcp_server, "serve_stdio", lambda slug, cfg: seen.append((slug, cfg.database.url))
    )
    result = cli.invoke(app, ["mcp", "--tenant", "alice"])
    assert result.exit_code == 0, result.output
    assert seen == [("alice", env.db_url)]


def test_console_entry_points(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-OPS-216: `main()` and `python -m victus` run the app under the name `victus`."""
    monkeypatch.setattr(sys, "argv", ["victus", "version"])
    with pytest.raises(SystemExit) as direct:
        cli_main.main()
    assert direct.value.code == 0
    monkeypatch.setattr(sys, "argv", ["victus", "--version"])
    with pytest.raises(SystemExit) as module:
        runpy.run_module("victus", run_name="__main__")
    assert module.value.code == 0
    assert capsys.readouterr().out.splitlines() == [f"victus {__version__}"] * 2


# ── agent group ──────────────────────────────────────────────────────────────


def test_agent_run_processes_in_process(env: CliEnv) -> None:
    """T-OPS-217: `agent run` queues and processes a run; bad input exits 2 and queues nothing."""
    result = cli.invoke(
        app,
        ["agent", "run", "--tenant", "alice", "--from", "2026-01-05", "--to", "2026-01-06"],
    )
    # No model is configured, so the run is processed to a clean "failed" and exits 1.
    [run] = _runs(env)
    assert run.status == "failed"
    assert result.exit_code == 1
    assert "no model configured" in result.stdout
    assert f"run {run.id}: failed, 0 day(s), 0/0 tokens, 0.00 USD" in result.stderr

    for args, message in (
        (["--tenant", "nobody"], "tenant 'nobody' not found"),
        (["--tenant", "alice", "--from", "05.01.2026"], "--from must be YYYY-MM-DD"),
        (["--tenant", "alice", "--mode", "nonsense"], "mode"),
        (["--tenant", "alice", "--captures", "cap_missing, ,"], "capture cap_missing not found"),
        (["--tenant", "alice", "--from", "2026-01-06", "--to", "2026-01-05"], "'to'"),
    ):
        bad = cli.invoke(app, ["agent", "run", *args])
        assert bad.exit_code == 2, (args, bad.output)
        assert message in bad.output, (args, bad.output)
    assert len(_runs(env)) == 1


@dataclass
class _FakeRun:
    status: str
    input_tokens: int = 1200
    output_tokens: int = 300
    cost_usd: float = 0.125


@dataclass
class _FakeOutcome:
    run: _FakeRun
    days: list[object] = field(default_factory=lambda: [object()])
    summary_md: str = "# Summary\n\none day drafted"


@pytest.mark.parametrize(
    ("outcome", "exit_code", "stderr_part"),
    [
        (None, 1, "failed (see logs)"),
        (_FakeOutcome(_FakeRun("finished")), 0, "finished, 1 day(s), 1200/300 tokens, 0.12 USD"),
        (_FakeOutcome(_FakeRun("failed")), 1, "failed, 1 day(s)"),
        (_FakeOutcome(_FakeRun("budget_exceeded")), 1, "budget_exceeded, 1 day(s)"),
    ],
)
def test_agent_run_exit_codes(
    env: CliEnv,
    monkeypatch: pytest.MonkeyPatch,
    outcome: _FakeOutcome | None,
    exit_code: int,
    stderr_part: str,
) -> None:
    """T-OPS-218: `agent run` exits 0 on a finished run, 1 on a lost, failed or over-budget run."""
    monkeypatch.setattr(Worker, "process_run", lambda self, tenant_id, run_id: outcome)
    result = cli.invoke(app, ["agent", "run", "--tenant", "alice", "--mode", "batch"])
    assert result.exit_code == exit_code, result.output
    assert stderr_part in result.stderr
    if outcome is not None:
        assert "one day drafted" in result.stdout


def test_agent_runs_and_unlock(env: CliEnv) -> None:
    """T-OPS-219: `agent runs` lists newest runs; `agent unlock` drops a held lock; a bad
    date exits 2."""
    empty = cli.invoke(app, ["agent", "runs", "--tenant", "alice"])
    assert empty.exit_code == 0
    assert empty.stdout.strip() == "no runs"

    engine, s = _session(env)
    try:
        tenant = s.scalar(select(orm.Tenant).where(orm.Tenant.slug == "alice"))
        assert tenant is not None
        s.add(
            orm.AgentRun(
                tenant_id=tenant.id,
                runner="worker",
                mode="historical",
                status="queued",
                captures=[],
                days=["2026-01-05"],
            )
        )
        s.add(
            orm.AgentLock(
                tenant_id=tenant.id,
                date=date(2026, 1, 5),
                runner="worker",
                run_id="run-x",
                locked_until=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        s.commit()
    finally:
        s.close()
        engine.dispose()

    listed = cli.invoke(app, ["agent", "runs", "--tenant", "alice", "--limit", "5"])
    assert listed.exit_code == 0
    header, row = listed.stdout.strip().splitlines()
    assert header.split()[:6] == ["id", "status", "mode", "runner", "days", "usd"]
    assert row.split()[1:6] == ["queued", "historical", "worker", "1", "0.00"]

    released = cli.invoke(app, ["agent", "unlock", "--tenant", "alice", "--date", "2026-01-05"])
    assert released.exit_code == 0
    assert released.stdout.strip() == "2026-01-05: lock released"
    again = cli.invoke(app, ["agent", "unlock", "--tenant", "alice", "--date", "2026-01-05"])
    assert again.stdout.strip() == "2026-01-05: no lock held"

    bad = cli.invoke(app, ["agent", "unlock", "--tenant", "alice", "--date", "Jan 5"])
    assert bad.exit_code == 2
    assert "--date must be YYYY-MM-DD" in bad.output
    unknown = cli.invoke(app, ["agent", "runs", "--tenant", "nobody"])
    assert unknown.exit_code == 2
