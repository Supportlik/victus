"""T-API-100…103: every REST route declares the scopes its use case enforces.

``victus.api.scopes.ROUTE_SCOPES`` is the declaration; ``current_context`` refuses a request
against it before the route runs, and the use case checks again. These tests hold the two
together for every route: the smallest scope sets the declaration names succeed, and each
set with one scope taken away is refused — once by the route check and once, with that
check switched off, by the use case itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI

from tests.integration.api.scope_env import REQUESTS, Env, send
from victus.api.app import create_app
from victus.api.deps import Principal, current_context, current_principal
from victus.api.scopes import ROUTE_SCOPES, route_key
from victus.application.tenant_context import ALL_SCOPES, SCOPE_ADMIN, TenantContext
from victus.config.server import ServerConfig
from victus.infrastructure.migrations import runner
from victus.infrastructure.transcription.fake import FakeTranscription

pytestmark = pytest.mark.api

SCOPED = sorted(k for k, v in ROUTE_SCOPES.items() if v.requires.groups)


def _accepted_cases() -> list[tuple[str, frozenset[str]]]:
    return [(k, s) for k in SCOPED for s in ROUTE_SCOPES[k].requires.minimal_sets()]


def _refused_cases() -> list[tuple[str, frozenset[str]]]:
    """Each minimal set with one scope removed; an emptied set gets an unrelated scope."""
    cases: set[tuple[str, frozenset[str]]] = set()
    for key in SCOPED:
        requires = ROUTE_SCOPES[key].requires
        filler = sorted(ALL_SCOPES - requires.scopes - {SCOPE_ADMIN})
        for minimal in requires.minimal_sets():
            for scope in minimal:
                held = minimal - {scope}
                if not held:
                    held = frozenset(filler[:1])
                if not requires.allows_scopes(held):
                    cases.add((key, held))
    return sorted(cases, key=lambda c: (c[0], sorted(c[1])))


def _id(case: tuple[str, frozenset[str]]) -> str:
    return f"{case[0]} [{','.join(sorted(case[1])) or '-'}]"


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    tmp = tmp_path_factory.mktemp("route-scopes")
    config = ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": f"sqlite:///{(tmp / 'scopes.db').as_posix()}"},
        storage={"path": str(tmp / "blobs")},
        auth={"rp_id": "localhost", "origin": "http://localhost", "session_ttl_days": 30},
        mcp={"rate_limit_per_minute": 100_000},
        events={"enabled": False},
    )
    app = create_app(config)
    runner.upgrade(engine=app.state.engine)
    app.state.transcription = FakeTranscription("one apple")
    yield Env(app)
    app.state.engine.dispose()


def _without_route_check(app: FastAPI) -> None:
    def ctx_only(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> TenantContext:
        return principal.ctx

    app.dependency_overrides[current_context] = ctx_only


def test_t_api_100_every_route_is_declared(env: Env) -> None:
    """T-API-100: the route table names every route of the app, and a request for each."""
    paths = env.client.get("/api/v1/openapi.json").json()["paths"]
    routes = {route_key(method, path) for path, ops in paths.items() for method in ops}
    assert routes == set(ROUTE_SCOPES), "a route without a scope declaration, or a stale one"
    assert set(SCOPED) == set(REQUESTS), "every scoped route needs a request in scope_env"


@pytest.mark.parametrize("case", _accepted_cases(), ids=_id)
def test_t_api_101_minimal_scopes_are_enough(env: Env, case: tuple[str, frozenset[str]]) -> None:
    """T-API-101: each smallest scope set the declaration names gets past every check."""
    key, scopes = case
    req = REQUESTS[key](env)
    r = send(env, req, env.headers(scopes))
    assert r.status_code < 300 or r.status_code in req.also_ok, (
        f"{key} with {sorted(scopes)}: {r.status_code} {r.text}"
    )


@pytest.mark.parametrize("case", _refused_cases(), ids=_id)
def test_t_api_102_route_refuses_a_missing_scope(
    env: Env, case: tuple[str, frozenset[str]]
) -> None:
    """T-API-102: one scope short of the declaration is a 403 naming what is missing."""
    key, scopes = case
    req = REQUESTS[key](env)
    r = send(env, req, env.headers(scopes))
    assert r.status_code == 403, f"{key} with {sorted(scopes)}: {r.status_code} {r.text}"
    assert "required" in r.json()["detail"]


@pytest.mark.parametrize("case", _refused_cases(), ids=_id)
def test_t_api_103_use_case_refuses_a_missing_scope(
    env: Env, case: tuple[str, frozenset[str]]
) -> None:
    """T-API-103: with the route check off, the use case refuses the same request itself."""
    key, scopes = case
    req = REQUESTS[key](env)
    _without_route_check(env.app)
    try:
        r = send(env, req, env.headers(scopes))
    finally:
        env.app.dependency_overrides.clear()
    assert r.status_code == 403, f"{key} with {sorted(scopes)}: {r.status_code} {r.text}"


def test_scope_env_has_no_stray_paths() -> None:
    """T-API-100: the request catalogue lives next to this test and names real routes only."""
    assert Path(__file__).with_name("scope_env.py").exists()
    assert set(REQUESTS) <= set(ROUTE_SCOPES)
