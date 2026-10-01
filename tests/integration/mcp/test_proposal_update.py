"""T-MCP-150…153: the agent corrects its own pending proposal; a draft item changes meal."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any, cast

import pytest

from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.mcp.tools import ToolContext, ToolError, dispatch, tools_for

AGENT = frozenset(
    {SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE}
)
DAY = date(2026, 3, 16)


def _as(tool_ctx: ToolContext, token_id: str, scopes: frozenset[str]) -> ToolContext:
    ctx = dataclasses.replace(tool_ctx.ctx, token_id=token_id, scopes=scopes)
    return dataclasses.replace(tool_ctx, ctx=ctx)


def _propose(tc: ToolContext, skyr: int, changes: dict[str, Any]) -> str:
    out = cast(
        dict[str, Any],
        dispatch(tc, "product_propose", {"product_id": skyr, "changes": changes}),
    )
    return str(out["id"])


@pytest.mark.covers("mcp:proposal_update")
def test_t_mcp_150_the_agent_corrects_its_own_proposal(tool_ctx: ToolContext, skyr: int) -> None:
    """T-MCP-150: `proposal_update` merges into the agent's pending proposal; nothing applies."""
    agent = _as(tool_ctx, "tok_agent", AGENT)
    proposal = _propose(agent, skyr, {"kcal": 70, "protein": 12})
    out = cast(
        dict[str, Any],
        dispatch(
            agent,
            "proposal_update",
            {
                "proposal_id": proposal,
                "changes": {"kcal": 67, "protein": None},
                "rationale": "the 7 was a 1 on the photo",
            },
        ),
    )
    assert out["status"] == "pending" and out["changes"] == {"kcal": 67}
    assert out["proposed"] is None, "still the agent's own reading, not a person's correction"
    assert out["rationale"] == "the 7 was a 1 on the photo"
    product = cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": skyr}))
    assert product["kcal"] == 63


def test_t_mcp_151_not_someone_elses_and_not_after_a_person(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-151: another token's proposal is forbidden; one a person corrected is a conflict."""
    agent = _as(tool_ctx, "tok_agent", AGENT)
    other = _as(tool_ctx, "tok_other", AGENT)
    theirs = _propose(other, skyr, {"fat": 1})
    with pytest.raises(ToolError) as refused:
        dispatch(agent, "proposal_update", {"proposal_id": theirs, "changes": {"fat": 2}})
    assert refused.value.code == "forbidden"

    mine = _propose(agent, skyr, {"kcal": 70})
    prop_uc.AmendProposal(factory, alice).execute(mine, {"kcal": 66})
    with pytest.raises(ToolError) as corrected:
        dispatch(agent, "proposal_update", {"proposal_id": mine, "changes": {"kcal": 71}})
    assert corrected.value.code == "Conflict"
    with pytest.raises(ToolError) as bad:
        dispatch(agent, "proposal_update", {"proposal_id": theirs, "changes": {"verified": 3}})
    assert bad.value.code == "forbidden"  # whose it is is decided before what it says


def test_t_mcp_152_the_tool_by_scope_set(tool_ctx: ToolContext, skyr: int) -> None:
    """T-MCP-152: callable with agent:write or approve; refused before running without."""
    proposal = _propose(_as(tool_ctx, "tok_agent", AGENT), skyr, {"kcal": 70})
    for scopes in (frozenset({SCOPE_READ}), frozenset({SCOPE_READ, SCOPE_WRITE})):
        tc = _as(tool_ctx, "tok_agent", scopes)
        assert "proposal_update" not in {t.name for t in tools_for(tc.ctx)}
        with pytest.raises(ToolError) as refused:
            dispatch(tc, "proposal_update", {"proposal_id": proposal, "changes": {"kcal": 1}})
        assert refused.value.code == "forbidden"
    # the full scope set is a person's: any pending proposal, the original kept
    out = cast(
        dict[str, Any],
        dispatch(tool_ctx, "proposal_update", {"proposal_id": proposal, "changes": {"kcal": 65}}),
    )
    assert out["changes"] == {"kcal": 65} and out["proposed"] == {"kcal": 70}
    with pytest.raises(ToolError) as invalid:
        dispatch(tool_ctx, "proposal_update", {"proposal_id": proposal})
    assert invalid.value.code == "validation"


def test_t_mcp_153_a_draft_item_changes_meal(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-153: `line_item_update` takes `meal_id`, within the day only."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    breakfast = day_uc.AddMeal(factory, alice).execute(DAY, "Breakfast").id
    lunch = day_uc.AddMeal(factory, alice).execute(DAY, "Lunch").id
    agent = _as(tool_ctx, "tok_agent", AGENT)
    item = cast(
        dict[str, Any],
        dispatch(
            agent,
            "line_item_create",
            {
                "date": DAY.isoformat(),
                "meal": "Breakfast",
                "consumable_id": skyr,
                "amount": 1,
                "unit_code": "tub",
            },
        ),
    )
    assert item["is_draft"] is True and item["meal_id"] == breakfast
    moved = cast(
        dict[str, Any],
        dispatch(agent, "line_item_update", {"line_item_id": item["id"], "meal_id": lunch}),
    )
    assert moved["meal_id"] == lunch
    with pytest.raises(ToolError) as elsewhere:
        dispatch(agent, "line_item_update", {"line_item_id": item["id"], "meal_id": 99_999})
    assert elsewhere.value.code == "NotFound"
