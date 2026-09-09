"""``victus`` command line entry point.

Process-level commands (``serve``, ``worker``, ``mcp``, ``migrate``) plus the
command groups for administration, backup and agent runs. A command that is not
implemented yet exits with code 3 and says which stage delivers it, so scripts
fail loudly instead of silently doing nothing.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from victus import __version__
from victus.cli.admin_cmd import passkey_app, tenant_app, token_app, user_app
from victus.cli.agent_cmd import agent_app, mcp_command, worker_command
from victus.cli.backup_cmd import backup_app

app = typer.Typer(
    name="victus",
    help="Self-hosted nutrition tracking: API, web app, reports, agent inbox, MCP.",
    no_args_is_help=True,
    add_completion=False,
)

NOT_IMPLEMENTED_EXIT = 3


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"victus {__version__}")
        raise typer.Exit()


VersionFlag = Annotated[
    bool,
    typer.Option(
        "--version",
        "-V",
        help="Show the version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
]


@app.callback()
def _root(version: VersionFlag = False) -> None:
    """Victus command line."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"victus {__version__}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes (dev only).")] = False,
    migrate: Annotated[bool, typer.Option(help="Run database migrations first.")] = True,
) -> None:
    """Run the HTTP API (and the mounted web app / MCP endpoint)."""
    import uvicorn

    if migrate:
        _migrate_database()
    # X-Forwarded-Proto is trusted, because the API is never exposed directly: it binds
    # localhost and a reverse proxy terminates TLS. Without this the app thinks every
    # request is plain HTTP, and `/mcp` redirects to `http://…/mcp/` — a client that
    # follows that lands on the web app and reads HTML where it expects JSON.
    uvicorn.run(
        "victus.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


def _planned(stage: str, what: str) -> None:
    typer.echo(f"victus: '{what}' is planned for {stage} and not implemented yet.", err=True)
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT)


@app.command()
def worker(
    once: Annotated[
        bool, typer.Option("--once", help="Process the queue a single time and exit.")
    ] = False,
) -> None:
    """Run the background worker: queued agent runs plus the optional cron trigger."""
    worker_command(once)


@app.command()
def mcp(
    tenant: Annotated[str, typer.Option("--tenant", help="Tenant slug the tools act for.")],
) -> None:
    """Serve the MCP tools over stdio for one tenant (trusted local process)."""
    mcp_command(tenant)


def _migrate_database() -> None:
    from victus.config.server import load_server_config
    from victus.infrastructure.migrations import runner

    cfg = load_server_config()
    runner.upgrade(cfg.database.url)
    typer.echo(f"migrations: up to date ({runner.current(cfg.database.url)})", err=True)


@app.command()
def migrate() -> None:
    """Apply database migrations (Alembic, to head)."""
    _migrate_database()


app.add_typer(backup_app, name="backup")
app.add_typer(token_app, name="token")
app.add_typer(tenant_app, name="tenant")
app.add_typer(user_app, name="user")
app.add_typer(passkey_app, name="passkey")
app.add_typer(agent_app, name="agent")


def main() -> None:
    """Console-script entry point."""
    try:
        app(prog_name="victus")
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
