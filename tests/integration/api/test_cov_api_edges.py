"""T-API-327…334: edges of the HTTP layer — app wiring, auth and error plumbing, uploads, SSE."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from tests.integration.api.conftest import Account
from tests.integration.api.cov_support import (
    API,
    assert_problem,
    line_item,
    product,
    put_settings,
)
from victus.api import deps
from victus.api.app import create_app
from victus.api.errors import problem
from victus.api.middleware import RateLimitMiddleware, TokenBucket
from victus.api.routers import captures as captures_router
from victus.api.routers import events as events_router
from victus.api.schemas.common import MacrosOut, macros_dict
from victus.application.tenant_context import ScopeError, TenantContext
from victus.application.use_cases._base import UowFactory
from victus.config.server import EventsConfig, ServerConfig, load_server_config
from victus.infrastructure.auth.sessions import SESSION_COOKIE
from victus.infrastructure.transcription.openai_transcribe import OpenAITranscription

pytestmark = pytest.mark.api

DAY = "2026-04-07"


def test_t_api_327_an_openai_key_wires_the_transcription_adapter(tmp_path: Path) -> None:
    """T-API-327: with a provider key the app builds the OpenAI adapter with the configured
    model and limit; without one there is none."""
    cfg = ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path)},
        providers={"openai_api_key": "sk-test"},
        transcription={"model": "whisper-1", "max_file_mb": 7},
    )
    app = create_app(cfg)
    try:
        adapter = app.state.transcription
        assert isinstance(adapter, OpenAITranscription)
        assert adapter.model == "whisper-1" and adapter.max_file_mb == 7
    finally:
        app.state.engine.dispose()


@pytest.mark.covers("GET /api/v1/days/{day}", "POST /api/v1/auth/logout")
def test_t_api_328_unknown_session_cookie_and_logout_without_one(
    client: TestClient,
) -> None:
    """T-API-328: a session cookie nobody issued is no principal (401, not 500); logging out
    without a cookie still answers 204 and clears it."""
    client.cookies.set(SESSION_COOKIE, "no-such-session")
    assert_problem(client.get(f"{API}/days/{DAY}"), 401)
    client.cookies.clear()
    r = client.post(f"{API}/auth/logout")
    assert r.status_code == 204
    assert SESSION_COOKIE in r.headers.get("set-cookie", "")


@pytest.mark.covers("POST /api/v1/auth/webauthn/login/verify")
def test_t_api_329_a_ceremony_without_its_id_is_refused(client: TestClient) -> None:
    """T-API-329: a WebAuthn verification without ``ceremony_id`` is a validation error."""
    r = client.post(
        f"{API}/auth/webauthn/login/verify",
        json={"id": "x", "rawId": "x", "type": "public-key", "response": {}},
    )
    assert r.status_code in (400, 422), r.text
    assert r.headers["content-type"].startswith("application/problem+json")


def test_t_api_330_scope_dependency_problem_and_rate_limit_plumbing() -> None:
    """T-API-330: ``require_scope`` passes a holder and refuses the rest; a problem without
    detail carries none; a ``PermissionError`` becomes 404; an empty token bucket refuses and
    the middleware answers 429 with ``Retry-After``."""
    dep = deps.require_scope("read")
    holder = TenantContext(tenant_id="t", scopes=frozenset({"read"}))
    assert dep(holder) is holder
    with pytest.raises(ScopeError):
        dep(TenantContext(tenant_id="t", token_id="tok", scopes=frozenset()))

    assert b"detail" not in problem(404, None).body

    bucket = TokenBucket(1)
    assert bucket.allow("k", now=0.0) is True
    assert bucket.allow("k", now=0.0) is False

    app = FastAPI()
    from victus.api.errors import install_error_handlers

    install_error_handlers(app)

    @app.get("/api/v1/captures")
    def _limited() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/foreign")
    def _foreign() -> None:
        raise PermissionError("row belongs to another tenant")

    app.add_middleware(RateLimitMiddleware, rate_per_minute=1)
    with TestClient(app) as c:
        assert c.get("/api/v1/captures").status_code == 200
        limited = c.get("/api/v1/captures")
        assert limited.status_code == 429 and limited.headers["retry-after"] == "30"
        foreign = c.get("/foreign")
        assert foreign.status_code == 404 and foreign.json()["detail"] == "not found"


def test_t_api_331_settings_file_and_macros_helpers(tmp_path: Path) -> None:
    """T-API-331: a settings file whose top level is not a mapping is refused by name; empty
    macros serialise as an empty object and an all-null ``MacrosOut``."""
    bad = tmp_path / "server.yaml"
    bad.write_text("- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="top level must be a mapping"):
        load_server_config(bad)
    assert macros_dict(None) == {}
    assert MacrosOut.from_macros(None) == MacrosOut()


@pytest.mark.covers(
    "PUT /api/v1/settings",
    "POST /api/v1/days/{day}",
    "GET /api/v1/days/{day}",
    "DELETE /api/v1/line-items/{item_id}",
    "DELETE /api/v1/products/{product_id}",
)
def test_t_api_332_day_target_band_item_and_product_delete(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-332: a day with a training type shows the band of the settings; a line item and
    an unused product are deleted (204) and gone afterwards."""
    put_settings(client, alice_token)
    r = client.post(
        f"{API}/days/{DAY}", json={"reliable": True, "training_type": "rest"}, headers=alice_token
    )
    assert r.status_code == 201, r.text
    band = client.get(f"{API}/days/{DAY}", headers=alice_token).json()["target_band"]
    assert band is not None and band["training_type"] == "rest"

    meal = client.post(f"{API}/days/{DAY}/meals", json={"name": "Lunch"}, headers=alice_token)
    oats = product(client, alice_token)
    item = line_item(client, alice_token, meal.json()["id"], oats, 30)["id"]
    assert client.delete(f"{API}/line-items/{item}", headers=alice_token).status_code == 204
    day = client.get(f"{API}/days/{DAY}", headers=alice_token).json()
    assert day["meals"][0]["line_items"] == []

    unused = product(client, alice_token, "Rye bread")
    assert client.delete(f"{API}/products/{unused}", headers=alice_token).status_code == 204
    assert_problem(client.get(f"{API}/products/{unused}", headers=alice_token), 404)


@pytest.mark.covers("POST /api/v1/captures")
def test_t_api_333_upload_limit_counts_all_parts_and_skips_empty_ones(
    client: TestClient, alice_token: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-API-333: parts that are each below the limit but together above it are 413; an
    empty file part is ignored rather than stored."""
    monkeypatch.setattr(captures_router, "MAX_UPLOAD_BYTES", 10)
    too_much = client.post(
        f"{API}/captures",
        files=[
            ("file", ("a.jpg", b"\xff\xd8" + b"1" * 6, "image/jpeg")),
            ("file", ("b.jpg", b"\xff\xd8" + b"2" * 6, "image/jpeg")),
        ],
        headers=alice_token,
    )
    assert_problem(too_much, 413)

    r = client.post(
        f"{API}/captures",
        data={"text": "a glass of milk"},
        files=[("file", ("empty.jpg", b"", "image/jpeg"))],
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "text"


def _request(headers: dict[str, str], disconnected: bool = False) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/events",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"} if disconnected else {"type": "http.request"}

    return Request(scope, receive)


def test_t_api_334_unreadable_last_event_id_falls_back(
    api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-334: a mangled ``Last-Event-ID`` falls back to ``?cursor=``; a negative one is
    clamped to 0; a client gone before the first poll ends the stream after the greeting."""
    assert events_router._resume_from(_request({"last-event-id": "abc"}), 7) == 7
    assert events_router._resume_from(_request({"last-event-id": "-4"}), None) == 0
    assert events_router._resume_from(_request({}), 3) == 3

    async def drain() -> list[str]:
        cfg = EventsConfig(enabled=True, poll_seconds=0.01, heartbeat_seconds=1)
        stream = events_router._stream(
            _request({}, disconnected=True), api_factory, alice_account.ctx, cfg, None
        )
        return [chunk async for chunk in stream]

    frames = anyio.run(drain)
    assert len(frames) == 1 and "event: hello" in frames[0]


def test_app_fixture_is_reused(api_app: FastAPI) -> None:
    """T-API-327: the package fixture's app has no transcription adapter without a key."""
    assert api_app.state.transcription is None
