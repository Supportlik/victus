"""Fixtures for the MCP tests: a tenant with a product, a tool context, an API app with /mcp."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from victus.api.app import create_app
from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.migrations import runner
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.mcp.server import make_tool_context
from victus.mcp.tools import ToolContext


@pytest.fixture
def config(tmp_path) -> ServerConfig:  # type: ignore[no-untyped-def]
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": "localhost", "origin": "http://localhost"},
        mcp={"http_enabled": True, "allowed_cidrs": [], "rate_limit_per_minute": 10_000},
    )


@pytest.fixture
def factory(session_factory: sessionmaker[Session]) -> UowFactory:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make


@pytest.fixture
def alice(tenants: tuple[TenantContext, TenantContext]) -> TenantContext:
    return TenantContext(tenant_id=tenants[0].tenant_id, scopes=ALL_SCOPES)


@pytest.fixture
def skyr(factory: UowFactory, alice: TenantContext) -> int:
    p = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Skyr natural", kcal=63, protein=11, carbs=4, fat=0.2, fiber=0, salt=0.1
        )
    )
    products_uc.AddPortion(factory, alice).execute(
        p.id, products_uc.PortionInput(unit_code="tub", label="tub", amount=400, is_default=True)
    )
    return p.id


@pytest.fixture
def tool_ctx(
    session_factory: sessionmaker[Session], alice: TenantContext, config: ServerConfig
) -> ToolContext:
    return make_tool_context(
        session_factory, alice, config, blobs=InMemoryBlobStorage(), transcription=None
    )


# ── HTTP: an API app with /mcp mounted, a tenant, tokens ──────────────────────


@pytest.fixture
def http_app(config: ServerConfig) -> Iterator[FastAPI]:
    application = create_app(config)
    runner.upgrade(engine=application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def http_factory(http_app: FastAPI) -> UowFactory:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(http_app.state.session_factory, ctx)

    return make


@pytest.fixture
def http_tenant(http_factory: UowFactory) -> TenantContext:
    tenant = tenants_uc.CreateTenant(http_factory, TenantContext(tenant_id="-")).execute(
        "alice", "Alice"
    )
    ctx = TenantContext(tenant_id=tenant.id, scopes=ALL_SCOPES)
    created = tenants_uc.CreateUser(http_factory, ctx).execute(
        "Alice", "alice@example.com", "owner"
    )
    return TenantContext(tenant_id=tenant.id, user_id=created.user.id)


@pytest.fixture
def make_token(http_factory: UowFactory, http_tenant: TenantContext) -> Callable[[list[str]], str]:
    def make(scopes: list[str]) -> str:
        return auth_uc.CreateToken(http_factory, http_tenant).execute("mcp", scopes, None).token

    return make
