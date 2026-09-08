"""``victus`` command line entry point.

Stage 0 ships the process-level commands (``serve``, ``version``) and registers
the command groups that later stages fill in. A group that is not implemented
yet exits with code 3 and says which stage delivers it, so scripts fail loudly
instead of silently doing nothing.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from victus import __version__

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
        # Alembic wiring arrives with Stage 1; until then this is a no-op that
        # keeps the deploy command line stable.
        typer.echo("migrations: none yet (Stage 1)", err=True)
    uvicorn.run("victus.api.app:create_app", factory=True, host=host, port=port, reload=reload)


def _planned(stage: str, what: str) -> None:
    typer.echo(f"victus: '{what}' is planned for {stage} and not implemented yet.", err=True)
    raise typer.Exit(code=NOT_IMPLEMENTED_EXIT)


import_app = typer.Typer(help="Import data from external sources (Stage 1).", no_args_is_help=True)
backup_app = typer.Typer(help="Create, verify and restore backups (Stage 1).", no_args_is_help=True)
token_app = typer.Typer(help="Manage API tokens (Stage 1).", no_args_is_help=True)
agent_app = typer.Typer(help="Run and inspect agent jobs (Stage 3).", no_args_is_help=True)


@import_app.command("vault")
def import_vault(
    path: Annotated[str, typer.Argument(help="Path to the Obsidian vault.")],
    tenant: Annotated[str, typer.Option(help="Tenant slug.")] = "default",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Parse and report only.")] = False,
) -> None:
    """Import products, recipes, day logs and weights from an Obsidian vault."""
    flags = " --dry-run" if dry_run else ""
    _planned("Stage 1", f"import vault {path} --tenant {tenant}{flags}")


@backup_app.command("create")
def backup_create() -> None:
    """Write a tenant backup archive."""
    _planned("Stage 1", "backup create")


@backup_app.command("verify")
def backup_verify() -> None:
    """Restore an archive into a temporary database and compare counts."""
    _planned("Stage 1", "backup verify")


@backup_app.command("restore")
def backup_restore() -> None:
    """Restore an archive."""
    _planned("Stage 1", "backup restore")


@backup_app.command("schedule")
def backup_schedule() -> None:
    """Run scheduled backups (daemon mode)."""
    _planned("Stage 1", "backup schedule")


@token_app.command("create")
def token_create() -> None:
    """Create an API token."""
    _planned("Stage 1", "token create")


@agent_app.command("run")
def agent_run() -> None:
    """Process open captures into day-log drafts."""
    _planned("Stage 3", "agent run")


@app.command()
def worker() -> None:
    """Run the background worker (scheduler, agent, weight sync)."""
    _planned("Stage 2", "worker")


@app.command()
def mcp() -> None:
    """Serve the MCP tools over stdio."""
    _planned("Stage 3", "mcp")


@app.command()
def migrate() -> None:
    """Apply database migrations."""
    _planned("Stage 1", "migrate")


app.add_typer(import_app, name="import")
app.add_typer(backup_app, name="backup")
app.add_typer(token_app, name="token")
app.add_typer(agent_app, name="agent")


def main() -> None:
    """Console-script entry point."""
    try:
        app(prog_name="victus")
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
