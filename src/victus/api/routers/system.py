"""System endpoints: health and version (no authentication)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from victus import __version__
from victus.application.use_cases.system import Health as HealthCheck

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str
    checks: dict[str, str]
    #: Hours since the newest successful backup finished; ``null`` when there never was one.
    backup_age_hours: float | None = None
    #: When the newest successful backup finished (UTC); ``null`` when there never was one.
    backup_last_at: datetime | None = None
    #: ``backup.max_age_hours``: an older backup, or none at all, makes ``checks.backup``
    #: read ``degraded``.
    backup_max_age_hours: int


class Version(BaseModel):
    version: str


@router.get("/health", response_model=Health, summary="Liveness and dependency checks")
def health(request: Request) -> Health:
    """Database, migrations, storage and backup age; ``status`` is ``ok`` or ``degraded``.

    ``checks.backup`` is ``degraded`` when no successful backup was ever recorded or the
    newest is older than ``backup.max_age_hours``; the answer stays ``200`` either way.
    """
    state = request.app.state
    result = HealthCheck(
        state.engine,
        state.session_factory,
        Path(state.config.storage.path),
        backup_max_age_hours=state.config.backup.max_age_hours,
    ).execute()
    return Health(
        status=result.status,
        version=result.version,
        checks=result.checks,
        backup_age_hours=result.backup_age_hours,
        backup_last_at=result.backup_last_at,
        backup_max_age_hours=result.backup_max_age_hours,
    )


@router.get("/version", response_model=Version, summary="Installed version")
def version() -> Version:
    return Version(version=__version__)
