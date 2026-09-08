"""System endpoints: health and version."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from victus import __version__

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str
    checks: dict[str, str]


class Version(BaseModel):
    version: str


@router.get("/health", response_model=Health, summary="Liveness and dependency checks")
def health() -> Health:
    """Report process health.

    Stage 1 adds database, storage and scheduler checks plus ``backup_age``;
    the shape of the response is fixed now so deploy healthchecks do not change.
    """
    return Health(status="ok", version=__version__, checks={"process": "ok"})


@router.get("/version", response_model=Version, summary="Installed version")
def version() -> Version:
    return Version(version=__version__)
