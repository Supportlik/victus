"""Fixtures for the runner/worker tests: config, tenant, a product, a tool context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import products as products_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription
from victus.mcp.server import make_tool_context
from victus.mcp.tools import ToolContext

DAY = date(2026, 3, 10)


@pytest.fixture
def config(tmp_path) -> ServerConfig:  # type: ignore[no-untyped-def]
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": "localhost", "origin": "http://localhost"},
        agent={"enabled": False, "cron": None, "poll_seconds": 1, "lock_ttl_minutes": 5},
        mcp={"allowed_cidrs": [], "rate_limit_per_minute": 10_000},
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
def bob(tenants: tuple[TenantContext, TenantContext]) -> TenantContext:
    return TenantContext(tenant_id=tenants[1].tenant_id, scopes=ALL_SCOPES)


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
def blobs() -> InMemoryBlobStorage:
    return InMemoryBlobStorage()


@pytest.fixture
def make_tool_ctx(
    session_factory: sessionmaker[Session], config: ServerConfig, blobs: InMemoryBlobStorage
) -> Callable[[TenantContext], ToolContext]:
    def make(ctx: TenantContext) -> ToolContext:
        return make_tool_context(
            session_factory,
            ctx,
            config,
            blobs=blobs,
            transcription=FakeTranscription("two slices of rye bread with butter"),
        )

    return make
