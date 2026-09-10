"""T-MCP-002 tools against the database, T-MCP-003 in-memory MCP client,
T-MCP-004 Streamable HTTP mount: bearer auth, scopes, CIDR allow-list, rate limit."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client.client import Client
from mcp.types import TextContent

from victus.application.tenant_context import (
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_READ,
    TenantContext,
)
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases._base import UowFactory
from victus.mcp.server import (
    NetworkGuard,
    RateLimiter,
    build_http_request_headers,
    build_server,
    client_ip,
)
from victus.mcp.tools import ToolContext, dispatch

DAY = date(2026, 3, 10)


# ── tools against the database ───────────────────────────────────────────────


def test_product_search_and_day_tools(
    tool_ctx: ToolContext, skyr: int, factory: UowFactory, alice: TenantContext
) -> None:
    found = dispatch(tool_ctx, "product_search", {"q": "skyr"})
    assert isinstance(found, dict)
    assert found["products"][0]["id"] == skyr
    assert found["products"][0]["portions"][0]["unit_code"] == "tub"
    exact = dispatch(tool_ctx, "product_search", {"q": "Skyr natural"})
    assert isinstance(exact, dict) and exact["matches"][0]["consumable_id"] == skyr

    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    created = dispatch(
        tool_ctx,
        "line_item_create",
        {
            "date": DAY.isoformat(),
            "meal": "Breakfast",
            "consumable_id": skyr,
            "amount": 1,
            "unit_code": "tub",
        },
    )
    assert isinstance(created, dict) and created["base_amount"] == 400
    day = dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()})
    assert isinstance(day, dict) and day["meals"][0]["name"] == "Breakfast"
    assert round(day["macros"]["kcal"]) == 252
    listed = dispatch(tool_ctx, "days_list", {"from": DAY.isoformat(), "to": DAY.isoformat()})
    assert isinstance(listed, list) and listed[0]["date"] == DAY.isoformat()


def test_agent_message_add_writes_a_verdict_without_a_draft(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-012: the day's verdict is reachable on its own, without drafting anything."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    started = dispatch(tool_ctx, "agent_run_start", {"mode": "manual", "dates": [DAY.isoformat()]})
    assert isinstance(started, dict)
    run_id = started["run_id"]
    written = dispatch(
        tool_ctx,
        "agent_message_add",
        {
            "run_id": run_id,
            "date": DAY.isoformat(),
            "kind": "summary",
            "content": "A quiet rest day, two ready meals and a pudding.",
        },
    )
    assert isinstance(written, dict) and written["role"] == "agent"
    day = dispatch(tool_ctx, "day_get", {"date": DAY.isoformat()})
    assert isinstance(day, dict) and day["status"] == "open" and not day["has_drafts"]
    assert day["verdict"] == "A quiet rest day, two ready meals and a pudding."


def test_report_render_markdown_and_json(tool_ctx: ToolContext) -> None:
    md = dispatch(tool_ctx, "report_render", {"name": "checkup", "period": "14d"})
    assert isinstance(md, str) and "#" in md
    data = dispatch(tool_ctx, "report_render", {"format": "json"})
    assert isinstance(data, dict) and "blocks" in data


def test_capture_get_returns_image_payload(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d4944415478da63f8ffff3f0300050001ff2b3a4c0000000049454e44ae426082"
    )
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(data=png, filename="label.png", mime="image/png", target_date=DAY)
    )
    result = dispatch(tool_ctx, "capture_get", {"id": cap.id})
    from victus.mcp.tools import ImageResult

    assert isinstance(result, ImageResult) and result.mime == "image/png"
    assert json.loads(result.text)["id"] == cap.id
    open_ = dispatch(tool_ctx, "captures_open", {})
    assert isinstance(open_, list) and [c["id"] for c in open_] == [cap.id]


# ── in-memory MCP client ────────────────────────────────────────────────────


def _run(coro: Any) -> Any:
    return anyio.run(lambda: coro)


def test_in_memory_client_lists_and_calls_tools(tool_ctx: ToolContext, skyr: int) -> None:
    server = build_server(lambda: tool_ctx)

    async def scenario() -> tuple[dict[str, Any], Any, Any]:
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            ok = await client.call_tool("product_search", {"q": "skyr"})
            missing = await client.call_tool("product_get", {"id": 999_999})
            return tools, ok, missing

    tools, ok, missing = _run(scenario())
    assert "product_search" in tools and "day_approve" in tools
    schema = tools["product_search"].input_schema
    assert schema["required"] == ["q"]
    assert "Free text" in schema["properties"]["q"]["description"]
    assert not ok.is_error
    text = ok.content[0]
    assert isinstance(text, TextContent) and json.loads(text.text)["products"][0]["id"] == skyr
    assert missing.is_error
    assert "NotFound" in missing.content[0].text  # type: ignore[union-attr]


def test_in_memory_client_scope_rejection(tool_ctx: ToolContext) -> None:
    tool_ctx.ctx = TenantContext(tenant_id=tool_ctx.ctx.tenant_id, scopes=frozenset({SCOPE_READ}))
    server = build_server(lambda: tool_ctx)

    async def scenario() -> Any:
        async with Client(server) as client:
            return await client.call_tool("day_approve", {"date": DAY.isoformat()})

    result = _run(scenario())
    assert result.is_error and "forbidden" in result.content[0].text  # type: ignore[union-attr]


# ── Streamable HTTP mount ───────────────────────────────────────────────────


def _rpc(method: str, params: dict[str, Any] | None = None, rid: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _call(client: TestClient, token: str | None, name: str, args: dict[str, Any]) -> Any:
    headers = (
        build_http_request_headers(token)
        if token
        else {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
    )
    return client.post(
        "/mcp", json=_rpc("tools/call", {"name": name, "arguments": args}), headers=headers
    )


def test_http_requires_bearer_token(http_app: FastAPI, http_tenant: TenantContext) -> None:
    with TestClient(http_app) as client:
        r = _call(client, None, "product_search", {"q": "x"})
        assert r.status_code == 401
        assert "Bearer" in r.headers.get("www-authenticate", "")
        r = _call(client, "vct_bogus.nope", "product_search", {"q": "x"})
        assert r.status_code == 401


def test_http_calls_tool_with_token_scopes(
    http_app: FastAPI, make_token: Callable[[list[str]], str]
) -> None:
    read = make_token([SCOPE_READ, SCOPE_CAPTURE_READ])
    with TestClient(http_app) as client:
        listed = client.post(
            "/mcp", json=_rpc("tools/list"), headers=build_http_request_headers(read)
        )
        assert listed.status_code == 200, listed.text
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert "product_search" in names
        ok = _call(client, read, "days_list", {"from": "2026-03-01", "to": "2026-03-31"})
        assert ok.status_code == 200, ok.text
        result = ok.json()["result"]
        assert result.get("isError") in (None, False)
        assert json.loads(result["content"][0]["text"]) == []
        denied = _call(client, read, "day_approve", {"date": DAY.isoformat()})
        assert denied.status_code == 200
        body = denied.json()["result"]
        assert body["isError"] is True and "forbidden" in body["content"][0]["text"]
        approve = make_token([SCOPE_READ, SCOPE_APPROVE])
        not_found = _call(client, approve, "day_approve", {"date": DAY.isoformat()})
        assert "NotFound" in not_found.json()["result"]["content"][0]["text"]


def test_http_cidr_allow_list_blocks_foreign_clients(
    config: Any, make_token: Callable[[list[str]], str], http_app: FastAPI
) -> None:
    guard: NetworkGuard = http_app.routes[-1].app  # type: ignore[attr-defined]
    assert isinstance(guard, NetworkGuard)
    guard.networks = [__import__("ipaddress").ip_network("10.0.0.0/8")]
    token = make_token([SCOPE_READ])
    with TestClient(http_app) as client:
        r = _call(client, token, "days_list", {"from": "2026-03-01", "to": "2026-03-02"})
        assert r.status_code == 403
        headers = {**build_http_request_headers(token), "X-Forwarded-For": "10.100.1.2"}
        # the test client's peer is not a private proxy, so the header is ignored → still 403
        r = client.post("/mcp", json=_rpc("tools/list"), headers=headers)
        assert r.status_code == 403


def test_client_ip_honours_forwarded_header_only_from_private_proxies() -> None:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 1),
        "headers": [(b"x-forwarded-for", b"10.64.1.1, 172.16.0.1")],
    }
    assert client_ip(scope) == "10.64.1.1"  # type: ignore[arg-type]
    scope["client"] = ("192.0.2.5", 1)  # documentation range: a public peer, header ignored
    assert client_ip(scope) == "192.0.2.5"  # type: ignore[arg-type]


def test_rate_limiter_sliding_window() -> None:
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("k", now=0.0) and limiter.allow("k", now=1.0)
    assert not limiter.allow("k", now=2.0)
    assert limiter.allow("k", now=61.5)  # first hit aged out


def test_http_rate_limit_returns_429(
    http_app: FastAPI, make_token: Callable[[list[str]], str]
) -> None:
    guard: NetworkGuard = http_app.routes[-1].app  # type: ignore[attr-defined]
    guard.limiter = RateLimiter(per_minute=1)
    token = make_token([SCOPE_READ])
    with TestClient(http_app) as client:
        assert (
            client.post(
                "/mcp", json=_rpc("tools/list"), headers=build_http_request_headers(token)
            ).status_code
            == 200
        )
        r = client.post("/mcp", json=_rpc("tools/list"), headers=build_http_request_headers(token))
        assert r.status_code == 429 and r.headers["Retry-After"] == "60"


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_mount_path_variants(
    http_app: FastAPI, make_token: Callable[[list[str]], str], path: str
) -> None:
    token = make_token([SCOPE_READ])
    with TestClient(http_app) as client:
        r = client.post(path, json=_rpc("tools/list"), headers=build_http_request_headers(token))
        assert r.status_code in (200, 307)
