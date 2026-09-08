"""FastAPI application factory.

Only the system router exists in Stage 0. Feature routers are added per stage
under ``victus.api.routers`` and mounted here; nothing in this module contains
business logic (see ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

from fastapi import FastAPI

from victus import __version__
from victus.api.routers import system
from victus.config.server import ServerConfig, load_server_config

API_PREFIX = "/api/v1"


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Build the application. ``config`` defaults to env + ``victus.yaml``."""
    cfg = config or load_server_config()
    app = FastAPI(
        title="Victus",
        version=__version__,
        description="Self-hosted nutrition tracking: API, reports, agent inbox and MCP.",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.config = cfg
    app.include_router(system.router, prefix=API_PREFIX)
    return app
