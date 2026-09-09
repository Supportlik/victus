"""T-MCP-001: the tool registry — schemas, scopes, Anthropic definitions, error mapping."""

from __future__ import annotations

import jsonschema
import pytest

from victus.application.tenant_context import (
    ALL_SCOPES,
    SCOPE_READ,
    TenantContext,
)
from victus.config.server import ServerConfig
from victus.mcp import tools
from victus.mcp.tools import (
    TOOLS,
    WORKER_TOOLS,
    ToolContext,
    ToolError,
    anthropic_tool_definitions,
    dispatch,
    get_tool,
    tools_for,
)

EXPECTED = {
    "product_search",
    "product_get",
    "product_usage",
    "product_versions",
    "product_version_create",
    "rule_delete",
    "rule_upsert",
    "rules_list",
    "recipe_get",
    "day_get",
    "days_list",
    "drafts_list",
    "day_thread_get",
    "day_message_add",
    "draft_summary",
    "report_render",
    "report_snapshot_create",
    "report_assess",
    "report_snapshot_get",
    "report_snapshots_list",
    "captures_open",
    "capture_get",
    "capture_mark",
    "agent_run_start",
    "agent_run_finish",
    "draft_create",
    "draft_discard",
    "day_approve",
    "line_item_create",
    "line_item_update",
    "line_item_delete",
    "line_item_approve",
    "meal_update",
    "meal_delete",
    "product_update",
    "product_propose",
    "product_create",
    "portion_create",
    "weight_add",
}


def _ctx(scopes: frozenset[str] = ALL_SCOPES) -> ToolContext:
    def boom(_: TenantContext) -> None:
        raise AssertionError("handler must not run")

    return ToolContext(
        uow_factory=boom,  # type: ignore[arg-type]
        ctx=TenantContext(tenant_id="t", scopes=scopes),
        config=ServerConfig(_env_file=None),  # type: ignore[call-arg]
    )


def test_registry_lists_every_documented_tool() -> None:
    assert {t.name for t in TOOLS} == EXPECTED
    assert WORKER_TOOLS <= EXPECTED
    assert "day_approve" not in WORKER_TOOLS and "draft_discard" not in WORKER_TOOLS


def test_every_input_schema_is_a_valid_object_schema() -> None:
    for spec in TOOLS:
        schema = spec.input_schema()
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object", spec.name
        if spec.input_schema_override is None:
            assert schema["additionalProperties"] is False, spec.name


def test_anthropic_definitions_are_strict_where_possible() -> None:
    defs = {d["name"]: d for d in anthropic_tool_definitions(list(TOOLS))}
    assert set(defs) == EXPECTED
    search = defs["product_search"]
    assert search["strict"] is True
    assert search["input_schema"]["additionalProperties"] is False
    # Anthropic's strict mode requires every property to be listed, nullable ones included
    assert set(search["input_schema"]["required"]) == {"q", "limit", "on"}
    assert "strict" not in defs["draft_create"]  # published schema carries $defs
    assert defs["draft_create"]["input_schema"]["required"] == [
        "run_id",
        "date",
        "source_captures",
        "meals",
    ]
    assert "from" in defs["days_list"]["input_schema"]["properties"]  # alias, not from_


def test_tools_for_filters_by_scope_and_name() -> None:
    read_only = TenantContext(tenant_id="t", scopes=frozenset({SCOPE_READ}))
    names = {t.name for t in tools_for(read_only)}
    assert "product_search" in names and "day_approve" not in names
    assert {t.name for t in tools_for(read_only, WORKER_TOOLS)} <= WORKER_TOOLS


def test_dispatch_rejects_missing_scope_before_running() -> None:
    with pytest.raises(ToolError) as exc:
        dispatch(_ctx(frozenset({SCOPE_READ})), "day_approve", {"date": "2026-03-10"})
    assert exc.value.code == "forbidden"


def test_dispatch_rejects_unknown_tool_and_bad_arguments() -> None:
    with pytest.raises(ToolError) as unknown:
        dispatch(_ctx(), "nope", {})
    assert unknown.value.code == "unknown_tool"
    with pytest.raises(ToolError) as invalid:
        dispatch(_ctx(), "product_search", {"limit": 5})
    assert invalid.value.code == "validation" and "q" in invalid.value.message


def test_get_tool_and_result_text() -> None:
    assert get_tool("day_get").scope == SCOPE_READ
    assert tools.result_text({"a": 1}) == '{"a": 1}'
    assert tools.result_text("md") == "md"
    img = tools.ImageResult(data_b64="AA==", mime="image/png", text="caption")
    assert tools.result_text(img) == "caption"


def test_jsonable_handles_dates_enums_and_dataclasses() -> None:
    from dataclasses import dataclass
    from datetime import date

    from victus.domain.values import CaptureKind

    @dataclass(frozen=True)
    class Row:
        day: date
        kind: CaptureKind

    assert tools.jsonable([Row(date(2026, 3, 10), CaptureKind.AUDIO)]) == [
        {"day": "2026-03-10", "kind": "audio"}
    ]
