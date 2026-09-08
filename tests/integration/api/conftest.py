"""API fixtures: app on an in-memory database, two tenants, a signed-in owner, tokens."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from victus.api.app import create_app
from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.auth.sessions import CSRF_HEADER
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.migrations import runner

RP_ID = "localhost"
ORIGIN = "http://localhost"


@pytest.fixture
def api_config(tmp_path) -> ServerConfig:  # type: ignore[no-untyped-def]
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": RP_ID, "origin": ORIGIN, "session_ttl_days": 30},
        mcp={"rate_limit_per_minute": 10_000},
    )


@pytest.fixture
def api_app(api_config: ServerConfig) -> Iterator[FastAPI]:
    application = create_app(api_config)
    runner.upgrade(engine=application.state.engine)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def api_factory(api_app: FastAPI) -> UowFactory:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(api_app.state.session_factory, ctx)

    return make


@dataclass
class Account:
    slug: str
    tenant_id: str
    user_id: str
    email: str
    recovery_code: str
    ctx: TenantContext


@pytest.fixture
def make_account(api_factory: UowFactory) -> Callable[[str], Account]:
    def make(slug: str) -> Account:
        tenant = tenants_uc.CreateTenant(api_factory, TenantContext(tenant_id="-")).execute(
            slug, slug.title()
        )
        ctx = TenantContext(tenant_id=tenant.id, scopes=ALL_SCOPES)
        created = tenants_uc.CreateUser(api_factory, ctx).execute(
            slug.title(), f"{slug}@example.com", "owner"
        )
        return Account(
            slug,
            tenant.id,
            created.user.id,
            created.user.email or "",
            created.recovery_code,
            TenantContext(tenant_id=tenant.id, user_id=created.user.id),
        )

    return make


@pytest.fixture
def alice_account(make_account: Callable[[str], Account]) -> Account:
    return make_account("alice")


@pytest.fixture
def bob_account(make_account: Callable[[str], Account]) -> Account:
    return make_account("bob")


@pytest.fixture
def client(api_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(api_app) as c:
        yield c


class Session:
    """A TestClient with a session cookie and the matching CSRF header."""

    def __init__(self, app: FastAPI, account: Account, recovery: bool = False) -> None:
        self.client = TestClient(app)
        r = self.client.post(
            "/api/v1/auth/recovery", json={"email": account.email, "code": account.recovery_code}
        )
        assert r.status_code == 200, r.text
        self.me = r.json()
        self.csrf = {CSRF_HEADER: self.me["csrf_token"]}
        self.account = account
        self.recovery = recovery

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self.client, name)


def bearer(api_factory: UowFactory, account: Account, scopes: list[str]) -> dict[str, str]:
    created = auth_uc.CreateToken(api_factory, account.ctx).execute("test", scopes, None)
    return {"Authorization": f"Bearer {created.token}"}


@pytest.fixture
def alice_token(api_factory: UowFactory, alice_account: Account) -> dict[str, str]:
    return bearer(api_factory, alice_account, sorted(ALL_SCOPES))


@pytest.fixture
def bob_token(api_factory: UowFactory, bob_account: Account) -> dict[str, str]:
    return bearer(api_factory, bob_account, sorted(ALL_SCOPES))
