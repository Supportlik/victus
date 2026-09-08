"""``victus backup …`` — create, verify, restore, list, prune and schedule backups.

Exit codes: 0 ok · 1 verification/restore mismatch · 2 input error.
Database and paths come from the server configuration (``victus.yaml`` / ``VICTUS_*``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from victus.backup.export import ExportError, create_backup, list_archives
from victus.backup.manifest import ManifestError
from victus.backup.restore import RestoreError, restore_backup
from victus.backup.retention import plan_retention
from victus.backup.schedule import CronError, run_scheduled
from victus.backup.verify import verify_backup
from victus.config.server import ServerConfig, load_server_config
from victus.infrastructure.db.engine import make_engine

backup_app = typer.Typer(help="Create, verify and restore backups.", no_args_is_help=True)

EXIT_MISMATCH = 1
EXIT_INPUT = 2


def _cfg() -> ServerConfig:
    return load_server_config()


def _target(cfg: ServerConfig, target: Path | None) -> Path:
    return (target or cfg.backup.path).expanduser()


def _archive_arg(
    cfg: ServerConfig, archive: Path | None, latest: bool, target: Path | None
) -> Path:
    if latest:
        found = list_archives(_target(cfg, target))
        if not found:
            typer.echo(f"no archives in {_target(cfg, target)}", err=True)
            raise typer.Exit(EXIT_INPUT)
        return found[0]
    if archive is None:
        typer.echo("give an archive path or --latest", err=True)
        raise typer.Exit(EXIT_INPUT)
    if not archive.is_file():
        candidate = _target(cfg, target) / archive.name
        if candidate.is_file():
            return candidate
        typer.echo(f"archive not found: {archive}", err=True)
        raise typer.Exit(EXIT_INPUT)
    return archive


@backup_app.command("create")
def create(
    tenant: Annotated[
        str | None, typer.Option(help="Tenant slug; omit or --all for every tenant.")
    ] = None,
    all_tenants: Annotated[bool, typer.Option("--all", help="Export every tenant.")] = False,
    target: Annotated[Path | None, typer.Option(help="Directory (default: backup.path).")] = None,
    snapshot: Annotated[
        bool, typer.Option("--snapshot/--no-snapshot", help="Add a SQLite snapshot.")
    ] = True,
) -> None:
    """Write a backup archive."""
    if tenant and all_tenants:
        typer.echo("--tenant and --all exclude each other", err=True)
        raise typer.Exit(EXIT_INPUT)
    cfg = _cfg()
    engine = make_engine(cfg.database.url)
    try:
        archive = create_backup(
            engine,
            _target(cfg, target),
            tenant,
            include_sqlite_snapshot=snapshot,
            storage_path=cfg.storage.path,
        )
    except ExportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INPUT) from exc
    finally:
        engine.dispose()
    m = archive.manifest
    typer.echo(
        f"{archive.path}  ({archive.size:,} bytes, {len(m.tables)} tables, {len(m.blobs)} blobs)"
    )
    for w in archive.warnings:
        typer.echo(f"  warning: {w}", err=True)


@backup_app.command("verify")
def verify(
    archive: Annotated[Path | None, typer.Argument(help="Archive to verify.")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Verify the newest archive.")] = False,
    target: Annotated[Path | None, typer.Option(help="Directory (default: backup.path).")] = None,
) -> None:
    """Restore into a temporary database and compare counts and hashes."""
    cfg = _cfg()
    path = _archive_arg(cfg, archive, latest, target)
    result = verify_backup(path)
    typer.echo(result.summary())
    if result.ok:
        rows = sum(result.tables.values())
        typer.echo(f"  {len(result.tables)} tables, {rows:,} rows, views ok")
    raise typer.Exit(0 if result.ok else EXIT_MISMATCH)


@backup_app.command("restore")
def restore(
    archive: Annotated[Path, typer.Argument(help="Archive to restore.")],
    as_slug: Annotated[
        str | None, typer.Option("--as", "--tenant", help="Restore under a new tenant slug.")
    ] = None,
    mode: Annotated[
        str, typer.Option(help="fail_if_exists | replace | merge_new")
    ] = "fail_if_exists",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Do everything, roll back at the end.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    target: Annotated[
        Path | None, typer.Option(help="Directory used to resolve a bare file name.")
    ] = None,
) -> None:
    """Restore an archive into the configured database."""
    if mode not in ("fail_if_exists", "replace", "merge_new"):
        typer.echo("mode must be fail_if_exists, replace or merge_new", err=True)
        raise typer.Exit(EXIT_INPUT)
    cfg = _cfg()
    path = _archive_arg(cfg, archive, False, target)
    if not dry_run and not yes:
        typer.confirm(f"Restore {path.name} into {cfg.database.url} (mode {mode})?", abort=True)
    engine = make_engine(cfg.database.url)
    try:
        result = restore_backup(
            path,
            engine,
            tenant_slug_override=as_slug,
            mode=mode,  # type: ignore[arg-type]
            dry_run=dry_run,
            storage_path=cfg.storage.path,
        )
    except (RestoreError, ManifestError) as exc:
        typer.echo(f"restore failed: {exc}", err=True)
        raise typer.Exit(EXIT_MISMATCH) from exc
    finally:
        engine.dispose()
    verb = "would restore" if dry_run else "restored"
    typer.echo(f"{verb} tenant(s) {', '.join(result.tenants)} from {path.name}")
    for name, n in result.counts_after.items():
        if n:
            typer.echo(f"  {name:<20} {n:>8,}")
    if result.blobs_restored:
        typer.echo(f"  blobs restored: {result.blobs_restored}")
    for w in result.warnings:
        typer.echo(f"  warning: {w}", err=True)


@backup_app.command("list")
def list_cmd(
    target: Annotated[Path | None, typer.Option(help="Directory (default: backup.path).")] = None,
) -> None:
    """List archives, newest first."""
    cfg = _cfg()
    found = list_archives(_target(cfg, target))
    if not found:
        typer.echo(f"no archives in {_target(cfg, target)}")
        return
    for p in found:
        typer.echo(f"{p.stat().st_size:>12,}  {p.name}")


@backup_app.command("prune")
def prune(
    target: Annotated[Path | None, typer.Option(help="Directory (default: backup.path).")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only show what would be deleted.")
    ] = False,
) -> None:
    """Apply the retention policy (backup.retention.*) now."""
    cfg = _cfg()
    r = cfg.backup.retention
    plan = plan_retention(_target(cfg, target), daily=r.daily, weekly=r.weekly, monthly=r.monthly)
    for p in plan.delete:
        typer.echo(f"{'would delete' if dry_run else 'deleting'}  {p.name}")
        if not dry_run:
            p.unlink(missing_ok=True)
    typer.echo(
        f"kept {len(plan.keep)}, {'would delete' if dry_run else 'deleted'} {len(plan.delete)}"
    )


@backup_app.command("schedule")
def schedule(
    daemon: Annotated[bool, typer.Option("--daemon", help="Run forever on backup.cron.")] = False,
    once: Annotated[
        bool, typer.Option("--once", help="Run one create+verify+prune cycle now.")
    ] = False,
    target: Annotated[Path | None, typer.Option(help="Directory (default: backup.path).")] = None,
) -> None:
    """Scheduled backups (the Compose `backup` service runs this with --daemon)."""
    if daemon == once:
        typer.echo("choose --daemon or --once", err=True)
        raise typer.Exit(EXIT_INPUT)
    cfg = _cfg()
    r = cfg.backup.retention
    engine = make_engine(cfg.database.url)
    try:
        outcomes = run_scheduled(
            engine,
            cron=cfg.backup.cron,
            target_dir=_target(cfg, target),
            storage_path=cfg.storage.path,
            retention=(r.daily, r.weekly, r.monthly),
            once=once,
            on_outcome=lambda o: typer.echo(
                f"{'ok' if o.ok else 'FAILED'} {o.archive.name if o.archive else '-'}"
                f"{' verified' if o.verified else ''}"
                f"{' deleted ' + str(len(o.deleted)) if o.deleted else ''}"
                f"{' ' + o.error if o.error else ''}"
            ),
        )
    except CronError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_INPUT) from exc
    finally:
        engine.dispose()
    if once and outcomes and not outcomes[0].ok:
        raise typer.Exit(EXIT_MISMATCH)
