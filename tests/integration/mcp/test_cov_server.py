"""T-MCP-230…239: the MCP server around the registry — content types, stdio, the HTTP guard.

What an MCP client receives for an image tool, how the stdio transport finds its tenant, and
how the network guard in front of ``/mcp`` treats addresses, missing tokens and non-HTTP
traffic. The tool handlers themselves are covered in ``test_cov_tools.py``.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent
from starlette.types import Receive, Scope, Send

from victus.api.app import create_app
from victus.application.tenant_context import ALL_SCOPES, SCOPE_READ, TenantContext
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.migrations import runner
from victus.infrastructure.transcription.openai_transcribe import OpenAITranscription
from victus.mcp.server import (
    NetworkGuard,
    RateLimiter,
    build_http_request_headers,
    build_server,
    client_ip,
    current_http_context,
    decode_image,
    parse_text,
    serve_stdio,
    stdio_context,
)
from victus.mcp.tools import ToolContext, ToolError, dispatch

DAY = date(2026, 3, 10)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63f8ffff3f0300050001ff2b3a4c0000000049454e44ae426082"
)


# ── content an MCP client receives ───────────────────────────────────────────


@pytest.mark.covers("mcp:capture_get")
def test_t_mcp_230_image_tool_returns_image_and_caption(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-230: capture_get over MCP is an image block plus a JSON caption block."""
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(data=PNG, filename="label.png", mime="image/png", target_date=DAY)
    )
    server = build_server(lambda: tool_ctx)

    async def scenario() -> Any:
        async with Client(server) as client:
            return await client.call_tool("capture_get", {"id": cap.id})

    result = anyio.run(scenario)
    assert not result.is_error
    image, caption = result.content
    assert isinstance(image, ImageContent) and image.mime_type == "image/png"
    assert decode_image(image) == PNG
    assert isinstance(caption, TextContent) and parse_text(caption)["id"] == cap.id


def test_t_mcp_231_parse_text_keeps_plain_text() -> None:
    """T-MCP-231: a text block that is not JSON (a Markdown report) comes back unchanged."""
    assert parse_text(TextContent(type="text", text="# Check-up")) == "# Check-up"
    assert parse_text(TextContent(type="text", text='{"a": 1}')) == {"a": 1}


# ── stdio ────────────────────────────────────────────────────────────────────


def _stdio_config(tmp_path: Path, **extra: Any) -> ServerConfig:
    return ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": f"sqlite:///{(tmp_path / 'victus.db').as_posix()}"},
        storage={"path": str(tmp_path / "blobs")},
        **extra,
    )


def _seed_tenant(config: ServerConfig, slug: str) -> str:
    engine = make_engine(config.database.url)
    try:
        runner.upgrade(engine=engine)
        with make_session_factory(engine)() as s:
            tenant = orm.Tenant(slug=slug, name=slug.title())
            s.add(tenant)
            s.commit()
            return tenant.id
    finally:
        engine.dispose()


@pytest.mark.covers("mcp:days_list")
def test_t_mcp_232_stdio_context_is_the_flagged_tenant_with_every_scope(tmp_path: Path) -> None:
    """T-MCP-232: the local process gets the tenant named by the flag, all scopes, no STT."""
    config = _stdio_config(tmp_path)
    tenant_id = _seed_tenant(config, "alice")
    tc = stdio_context("alice", config)
    assert tc.ctx.tenant_id == tenant_id and tc.ctx.scopes == ALL_SCOPES
    assert tc.ctx.token_id == "stdio:alice"
    assert tc.transcription is None and tc.blobs is not None
    assert dispatch(tc, "days_list", {"from": "2026-03-01", "to": "2026-03-31"}) == []


def test_t_mcp_233_stdio_context_with_an_openai_key_transcribes(tmp_path: Path) -> None:
    """T-MCP-233: a configured OpenAI key gives the stdio session a transcription adapter."""
    config = _stdio_config(
        tmp_path,
        providers={"openai_api_key": "sk-test-not-a-key"},
        transcription={"model": "whisper-1", "max_file_mb": 5, "ffmpeg_path": "ffmpeg"},
    )
    _seed_tenant(config, "alice")
    tc = stdio_context("alice", config)
    assert isinstance(tc.transcription, OpenAITranscription)
    assert tc.transcription.model == "whisper-1" and tc.transcription.max_file_mb == 5


def test_t_mcp_234_stdio_context_refuses_an_unknown_tenant(tmp_path: Path) -> None:
    """T-MCP-234: a tenant slug that does not exist stops the process with a clear message."""
    config = _stdio_config(tmp_path)
    _seed_tenant(config, "alice")
    with pytest.raises(SystemExit) as exc:
        stdio_context("bob", config)
    assert "tenant 'bob' not found" in str(exc.value)


def test_t_mcp_235_serve_stdio_runs_the_stdio_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-MCP-235: serve_stdio registers every tool and hands the server to the stdio loop."""
    config = _stdio_config(tmp_path)
    _seed_tenant(config, "alice")
    seen: dict[str, Any] = {}

    def fake_run(self: MCPServer, transport: str, **_: Any) -> None:
        seen["transport"] = transport
        seen["server"] = self

    monkeypatch.setattr(MCPServer, "run", fake_run)
    serve_stdio("alice", config)
    assert seen["transport"] == "stdio"

    async def names() -> set[str]:
        async with Client(seen["server"]) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert {"product_search", "day_approve", "capture_get"} <= anyio.run(names)


# ── HTTP: context, guard, mount ──────────────────────────────────────────────


def test_t_mcp_236_http_context_needs_a_victus_token() -> None:
    """T-MCP-236: outside an authenticated request there is no tenant to act for."""
    with pytest.raises(ToolError) as exc:
        current_http_context()
    assert exc.value.code == "unauthenticated"


class _Recorder:
    """A downstream ASGI app that answers 200 and remembers what reached it."""

    def __init__(self) -> None:
        self.scopes: list[str] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.scopes.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _hit(guard: NetworkGuard, scope: dict[str, Any]) -> int | None:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    anyio.run(guard, scope, receive, send)  # type: ignore[arg-type]
    return next((m["status"] for m in sent if m["type"] == "http.response.start"), None)


def _http(client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]] | None = None) -> Any:
    return {"type": "http", "path": "/", "client": client, "headers": headers or []}


def test_t_mcp_237_network_guard_addresses_and_rate_keys() -> None:
    """T-MCP-237: allowed and foreign peers, no peer, lifespan traffic, per-address limits."""
    app = _Recorder()
    guard = NetworkGuard(app, ["10.0.0.0/8"], RateLimiter(per_minute=1))
    assert _hit(guard, _http(("10.1.2.3", 1))) == 200, "inside the allow-list"
    assert _hit(guard, _http(("192.0.2.9", 1))) == 403, "outside it"
    assert _hit(guard, _http(None)) == 403, "an unknown peer is never allowed"
    assert _hit(guard, _http(("not-an-ip", 1))) == 403
    # without a bearer token the limit is kept per address: a second call from it is refused,
    # a call from another allowed address is not
    assert _hit(guard, _http(("10.1.2.3", 1))) == 429
    assert _hit(guard, _http(("10.9.9.9", 1))) == 200
    # non-HTTP traffic (the lifespan protocol) passes straight through
    assert _hit(guard, {"type": "lifespan"}) is None
    assert app.scopes == ["http", "http", "lifespan"]
    assert guard.networks == [ipaddress.ip_network("10.0.0.0/8")]


def test_t_mcp_238_client_ip_without_a_peer_or_with_a_malformed_one() -> None:
    """T-MCP-238: no peer trusts the forwarded header; a malformed peer is not a private proxy."""
    forwarded = [(b"x-forwarded-for", b"10.64.1.1")]
    assert client_ip(_http(None, forwarded)) == "10.64.1.1"
    assert client_ip(_http(None)) is None
    assert client_ip(_http(("testclient", 1), forwarded)) == "testclient"


@pytest.mark.covers("mcp:days_list")
def test_t_mcp_239_mount_without_an_origin_uses_the_rp_id(tmp_path: Path) -> None:
    """T-MCP-239: with no origin configured the MCP resource URL is built from the RP id."""
    config = ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": "victus.example.com"},
        mcp={"http_enabled": True, "allowed_cidrs": [], "rate_limit_per_minute": 10_000},
    )
    app: FastAPI = create_app(config)
    try:
        runner.upgrade(engine=app.state.engine)
        server: MCPServer = app.state.mcp_server
        auth = server.settings.auth
        assert auth is not None
        assert str(auth.issuer_url).rstrip("/") == "http://victus.example.com"
        assert str(auth.resource_server_url) == "http://victus.example.com/mcp"

        from victus.application.use_cases import auth as auth_uc
        from victus.application.use_cases import tenants as tenants_uc
        from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

        def factory(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(app.state.session_factory, ctx)

        tenant = tenants_uc.CreateTenant(factory, TenantContext(tenant_id="-")).execute(
            "alice", "Alice"
        )
        owner = TenantContext(tenant_id=tenant.id, scopes=ALL_SCOPES)
        user = tenants_uc.CreateUser(factory, owner).execute("Alice", "alice@example.com", "owner")
        token = (
            auth_uc.CreateToken(factory, TenantContext(tenant_id=tenant.id, user_id=user.user.id))
            .execute("mcp", [SCOPE_READ], None)
            .token
        )
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "days_list",
                "arguments": {"from": "2026-03-01", "to": "2026-03-02"},
            },
        }
        with TestClient(app) as client:
            r = client.post("/mcp", json=body, headers=build_http_request_headers(token))
        assert r.status_code == 200, r.text
        assert json.loads(r.json()["result"]["content"][0]["text"]) == []
    finally:
        app.state.engine.dispose()
