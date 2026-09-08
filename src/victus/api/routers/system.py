"""System endpoints: health and version (no authentication)."""

from __future__ import annotations

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
    backup_age_hours: float | None = None


class Version(BaseModel):
    version: str


@router.get("/health", response_model=Health, summary="Liveness and dependency checks")
def health(request: Request) -> Health:
    """Database, migrations, storage and backup age; ``status`` is ``ok`` or ``degraded``."""
    state = request.app.state
    result = HealthCheck(
        state.engine, state.session_factory, Path(state.config.storage.path)
    ).execute()
    return Health(
        status=result.status,
        version=result.version,
        checks=result.checks,
        backup_age_hours=result.backup_age_hours,
    )


@router.get("/version", response_model=Version, summary="Installed version")
def version() -> Version:
    return Version(version=__version__)
