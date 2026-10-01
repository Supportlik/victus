"""T-MCP-102…105: a token sees only the tools it may call; the tools whose declared scope
used to differ from their use case now behave as declared."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date
from typing import Any

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.client.client import Client

from victus.application.scope_profiles import PROFILES, WORKER, ScopeProfile
from victus.application.tenant_context import (
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.transcription.fake import FakeTranscription
from victus.mcp.server import build_http_request_headers, build_server
from victus.mcp.tools import TOOLS, ToolContext, ToolError, dispatch, tools_for

DAY = date(2026, 3, 10)


def _rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _with(tc: ToolContext, scopes: set[str]) -> ToolContext:
    return dataclasses.replace(
        tc, ctx=dataclasses.replace(tc.ctx, token_id="tok_test", scopes=frozenset(scopes))
    )


@pytest.mark.parametrize("profile", [p for p in PROFILES if p is not WORKER], ids=lambda p: p.key)
def test_t_mcp_102_http_lists_only_callable_tools(
    profile: ScopeProfile, http_app: FastAPI, make_token: Callable[[list[str]], str]
) -> None:
    """T-MCP-102: `tools/list` over HTTP is exactly the profile's callable tools."""
    token = make_token(list(profile.scopes))
    expected = {
        t.name for t in tools_for(TenantContext(tenant_id="-", scopes=frozenset(profile.scopes)))
    }
    with TestClient(http_app) as client:
        r = client.post("/mcp", json=_rpc("tools/list"), headers=build_http_request_headers(token))
        assert r.status_code == 200, r.text
        listed = {t["name"] for t in r.json()["result"]["tools"]}
    assert listed == expected
    if SCOPE_APPROVE not in profile.scopes:
        assert not {"day_approve", "line_item_approve", "draft_discard"} & listed


def test_t_mcp_102_hidden_tool_called_anyway_is_forbidden(
    http_app: FastAPI, make_token: Callable[[list[str]], str]
) -> None:
    """T-MCP-102: a tool missing from the list answers `forbidden` with the scope, no result."""
    token = make_token([SCOPE_CAPTURE_WRITE])
    with TestClient(http_app) as client:
        r = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "day_get", "arguments": {"date": DAY.isoformat()}}),
            headers=build_http_request_headers(token),
        )
    result = r.json()["result"]
    assert result["isError"] is True
    assert "forbidden: scope 'read' required" in result["content"][0]["text"]


def test_t_mcp_102_in_process_server_filters_per_context(tool_ctx: ToolContext) -> None:
    """T-MCP-102: the same filter applies to every transport — stdio holds every scope."""
    narrow = _with(tool_ctx, {SCOPE_READ})

    async def names(tc: ToolContext) -> set[str]:
        async with Client(build_server(lambda: tc)) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert anyio.run(names, tool_ctx) == {t.name for t in TOOLS}
    read_only = anyio.run(names, narrow)
    assert "day_get" in read_only and "draft_create" not in read_only
    assert "day_thread_get" not in read_only  # it carries captures


def test_t_mcp_103_capture_get_transcribes_only_with_capture_write(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-103: a read-only capture token gets audio as it stands; capture:write transcribes."""
    assert tool_ctx.blobs is not None
    cap = capture_uc.UploadCapture(factory, alice, tool_ctx.blobs).execute(
        capture_uc.UploadInput(data=b"OggS-fake", filename="note.oga", mime="audio/ogg")
    )
    fake = FakeTranscription("half a tub of skyr")
    reader = dataclasses.replace(_with(tool_ctx, {SCOPE_CAPTURE_READ}), transcription=fake)
    first = dispatch(reader, "capture_get", {"id": cap.id})
    assert isinstance(first, dict) and first["transcript"] is None and fake.calls == []
    writer = dataclasses.replace(
        _with(tool_ctx, {SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE}), transcription=fake
    )
    second = dispatch(writer, "capture_get", {"id": cap.id})
    assert isinstance(second, dict) and second["transcript"] == "half a tub of skyr"


def test_t_mcp_104_line_item_create_on_a_day_without_a_log(
    tool_ctx: ToolContext, skyr: int, factory: UowFactory, alice: TenantContext
) -> None:
    """T-MCP-104: a draft creates its draft day; a fact on a missing day is a clear error (R81)."""
    args = {"date": DAY.isoformat(), "meal": "Breakfast", "consumable_id": skyr, "amount": 1}
    deciding = _with(tool_ctx, {SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE})
    with pytest.raises(ToolError) as missing:
        dispatch(deciding, "line_item_create", {**args, "unit_code": "tub"})
    assert missing.value.code == "NotFound"
    assert "create the day first" in missing.value.message and "reliable" in missing.value.message

    drafting = _with(tool_ctx, {SCOPE_READ, SCOPE_WRITE})
    item = dispatch(drafting, "line_item_create", {**args, "unit_code": "tub"})
    assert isinstance(item, dict) and item["is_draft"] is True
    day = day_uc.GetDay(factory, alice).execute(DAY)
    assert day.status == "draft" and day.reliable is None
    assert [m.name for m in day.meals] == ["Breakfast"]

    # a second item lands in the same meal of the same draft day
    again = dispatch(
        drafting, "line_item_create", {**args, "unit_code": "tub", "meal": "breakfast"}
    )
    assert isinstance(again, dict)
    day = day_uc.GetDay(factory, alice).execute(DAY)
    assert len(day.meals) == 1 and len(day.meals[0].line_items) == 2
    with pytest.raises(ToolError) as blank:
        dispatch(drafting, "line_item_create", {**args, "unit_code": "tub", "meal": "  "})
    assert blank.value.code == "ValidationFailed"


def test_t_mcp_105_decisions_and_snapshots_need_their_scopes(
    tool_ctx: ToolContext, skyr: int
) -> None:
    """T-MCP-105: `day_approve` needs write + approve, `report_snapshot_create` needs write,
    and `product_propose`/`report_assess` accept write as well as agent:write."""
    approve_only = _with(tool_ctx, {SCOPE_READ, SCOPE_APPROVE})
    with pytest.raises(ToolError) as refused:
        dispatch(approve_only, "day_approve", {"date": DAY.isoformat(), "close": True})
    assert refused.value.code == "forbidden" and "'write'" in refused.value.message
    reader = _with(tool_ctx, {SCOPE_READ})
    with pytest.raises(ToolError) as frozen:
        dispatch(reader, "report_snapshot_create", {"name": "checkup"})
    assert frozen.value.code == "forbidden"
    writer = _with(tool_ctx, {SCOPE_READ, SCOPE_WRITE})
    snap = dispatch(writer, "report_snapshot_create", {"name": "checkup"})
    assert isinstance(snap, dict)
    assessed = dispatch(
        writer, "report_assess", {"snapshot_id": snap["id"], "assessment_md": "On track."}
    )
    assert isinstance(assessed, dict)
    proposed = dispatch(
        writer, "product_propose", {"product_id": skyr, "changes": {"kcal": 70}, "source": "label"}
    )
    assert isinstance(proposed, dict) and proposed["status"] == "pending"
