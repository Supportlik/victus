"""Agent commands: run, list runs, unlock a day; plus the worker and MCP entry points."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

import typer

from victus.application.errors import ApplicationError
from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.cli._db import uow_factory_from_config
from victus.config.server import ServerConfig, load_server_config

agent_app = typer.Typer(help="Run and inspect agent jobs.", no_args_is_help=True)

Tenant = Annotated[str, typer.Option("--tenant", help="Tenant slug.")]


def _resolve_tenant(slug: str, cfg: ServerConfig) -> tuple[str, TenantContext]:
    from sqlalchemy import select

    from victus.infrastructure.db import orm

    _, session_factory = uow_factory_from_config(cfg)
    with session_factory() as s:
        tenant = s.scalar(select(orm.Tenant).where(orm.Tenant.slug == slug))
        if tenant is None:
            raise typer.BadParameter(f"tenant '{slug}' not found")
        return tenant.id, TenantContext(tenant_id=tenant.id, scopes=ALL_SCOPES)


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"--{name} must be YYYY-MM-DD") from exc


@agent_app.command("run")
def agent_run(
    tenant: Tenant,
    mode: Annotated[
        str, typer.Option(help="historical | batch | manual | follow_up | assess")
    ] = "historical",
    captures: Annotated[
        str | None, typer.Option(help="Comma-separated capture ids (mode manual).")
    ] = None,
    from_: Annotated[str | None, typer.Option("--from", help="First day (YYYY-MM-DD).")] = None,
    to: Annotated[str | None, typer.Option("--to", help="Last day (YYYY-MM-DD).")] = None,
) -> None:
    """Queue a run and process it in this process; prints the summary."""
    from victus.agent.worker import Worker
    from victus.infrastructure.storage.fs_blob import FsBlobStorage
    from victus.mcp.server import _transcription_from

    cfg = load_server_config()
    tenant_id, ctx = _resolve_tenant(tenant, cfg)
    factory, session_factory = uow_factory_from_config(cfg)
    ids = [c.strip() for c in captures.split(",") if c.strip()] if captures else None
    try:
        run = agent_uc.QueueAgentRun(factory, ctx).execute(
            mode, captures=ids, start=_parse_date(from_, "from"), end=_parse_date(to, "to")
        )
    except ApplicationError as exc:
        raise typer.BadParameter(exc.detail) from exc
    worker = Worker(
        cfg,
        session_factory,
        blobs=FsBlobStorage(cfg.storage.path),
        transcription=_transcription_from(cfg),
    )
    outcome = worker.process_run(tenant_id, run.id)
    if outcome is None:
        typer.echo(f"run {run.id}: failed (see logs)", err=True)
        raise typer.Exit(code=1)
    typer.echo(outcome.summary_md)
    typer.echo(
        f"run {run.id}: {outcome.run.status}, {len(outcome.days)} day(s), "
        f"{outcome.run.input_tokens}/{outcome.run.output_tokens} tokens, "
        f"{outcome.run.cost_usd:.2f} USD",
        err=True,
    )
    if outcome.run.status in ("failed", "budget_exceeded"):
        raise typer.Exit(code=1)


@agent_app.command("runs")
def agent_runs(
    tenant: Tenant,
    limit: Annotated[int, typer.Option(help="Newest runs to show.")] = 20,
) -> None:
    """List recent agent runs of a tenant."""
    cfg = load_server_config()
    _, ctx = _resolve_tenant(tenant, cfg)
    factory, _ = uow_factory_from_config(cfg)
    runs = agent_uc.ListAgentRuns(factory, ctx).execute(limit=limit)
    if not runs:
        typer.echo("no runs")
        return
    typer.echo(
        f"{'id':<26} {'status':<16} {'mode':<11} {'runner':<9} {'days':<5} {'usd':>6}  created"
    )
    for r in runs:
        typer.echo(
            f"{r.id:<26} {r.status:<16} {r.mode:<11} {r.runner:<9} {len(r.days):<5} "
            f"{r.cost_usd:>6.2f}  {r.created_at.isoformat(timespec='minutes')}"
        )


@agent_app.command("unlock")
def agent_unlock(
    tenant: Tenant,
    day: Annotated[str, typer.Option("--date", help="Day to unlock (YYYY-MM-DD).")],
) -> None:
    """Drop a day's lock regardless of who holds it (operator escape hatch)."""
    cfg = load_server_config()
    _, ctx = _resolve_tenant(tenant, cfg)
    factory, _ = uow_factory_from_config(cfg)
    when = _parse_date(day, "date")
    assert when is not None
    released = agent_uc.ForceUnlockDay(factory, ctx).execute(when)
    typer.echo(f"{when.isoformat()}: {'lock released' if released else 'no lock held'}")


def worker_command(once: bool) -> None:
    """Body of ``victus worker``."""
    from victus.agent.worker import Worker
    from victus.infrastructure.storage.fs_blob import FsBlobStorage
    from victus.mcp.server import _transcription_from

    cfg = load_server_config()
    logging.basicConfig(
        level=cfg.server.log_level.upper(), format="%(asctime)s %(name)s %(message)s"
    )
    _, session_factory = uow_factory_from_config(cfg)
    worker = Worker(
        cfg,
        session_factory,
        blobs=FsBlobStorage(cfg.storage.path),
        transcription=_transcription_from(cfg),
    )
    if once:
        outcomes = worker.run_once()
        typer.echo(f"processed {len(outcomes)} run(s)", err=True)
        return
    worker.run_forever()


def mcp_command(tenant: str) -> None:
    """Body of ``victus mcp``: serve the tools over stdio for one tenant."""
    from victus.mcp.server import serve_stdio

    cfg = load_server_config()
    logging.basicConfig(level="WARNING")  # stdout is the protocol channel; keep logs on stderr
    serve_stdio(tenant, cfg)
