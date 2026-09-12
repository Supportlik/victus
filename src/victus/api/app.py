"""FastAPI application factory.

Wires configuration, database engine, authentication services and the
feature routers. No business logic lives here (see ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from victus import __version__
from victus.api.errors import install_error_handlers
from victus.api.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from victus.api.routers import (
    agent,
    auth,
    captures,
    days,
    drafts,
    events,
    master_data,
    placeholders,
    products,
    proposals,
    recipes,
    reports,
    settings,
    system,
    tenant,
    weight,
)
from victus.config.server import ServerConfig, load_server_config
from victus.infrastructure.auth.webauthn import InMemoryChallengeStore, WebAuthnService
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.storage.fs_blob import FsBlobStorage

API_PREFIX = "/api/v1"


def create_app(config: ServerConfig | None = None) -> FastAPI:
    """Build the application. ``config`` defaults to env + ``victus.yaml``."""
    cfg = config or load_server_config()
    engine = make_engine(cfg.database.url, echo=cfg.database.echo)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Victus",
        version=__version__,
        description="Self-hosted nutrition tracking: API, reports, agent inbox and MCP.",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.engine = engine
    app.state.session_factory = session_factory
    rp_id = cfg.auth.rp_id or "localhost"
    origin = cfg.auth.origin or f"http://{rp_id}"
    app.state.webauthn = WebAuthnService(rp_id, cfg.auth.rp_name, origin, InMemoryChallengeStore())
    app.state.blobs = FsBlobStorage(cfg.storage.path)
    app.state.transcription = None
    if cfg.providers.openai_api_key is not None:
        from victus.infrastructure.transcription.openai_transcribe import OpenAITranscription

        app.state.transcription = OpenAITranscription(
            cfg.providers.openai_api_key.get_secret_value(),
            cfg.transcription.model,
            max_file_mb=cfg.transcription.max_file_mb,
            ffmpeg_path=cfg.transcription.ffmpeg_path,
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware, rate_per_minute=cfg.mcp.rate_limit_per_minute)
    install_error_handlers(app)

    for router in (
        system.router,
        auth.router,
        tenant.router,
        master_data.router,
        products.router,
        proposals.router,
        recipes.router,
        reports.router,
        days.router,
        drafts.router,
        captures.router,
        events.router,
        agent.router,
        weight.router,
        settings.router,
        placeholders.router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    if cfg.mcp.http_enabled:
        # Streamable-HTTP MCP at /mcp (bearer token, CIDR allow-list); off by default.
        mcp_server = importlib.import_module("victus.mcp.server")
        mcp_server.mount_http(app, cfg)
    return app
