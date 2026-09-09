"""T-MCP-010: a whole day through MCP with a food that has no product yet (R81)."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.mcp.tools import ToolContext, ToolError, dispatch

DAY = date(2026, 3, 12)


@pytest.fixture
def agent_ctx(tool_ctx: ToolContext) -> ToolContext:
    """The same tool context, but with the scopes an agent token actually holds."""
    ctx = dataclasses.replace(
        tool_ctx.ctx,
        token_id="tok_agent",
        scopes=frozenset(
            {SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE}
        ),
    )
    return dataclasses.replace(tool_ctx, ctx=ctx)


def _factory(session_factory: sessionmaker[Session]) -> UowFactory:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make


def test_t_mcp_010_unknown_food_reaches_the_day_and_waits_for_the_person(
    agent_ctx: ToolContext,
    tool_ctx: ToolContext,
    session_factory: sessionmaker[Session],
    alice: TenantContext,
) -> None:
    """T-MCP-010: propose the product, draft the day against it, then a person approves both."""
    factory = _factory(session_factory)

    # 1. Nothing in the catalogue matches what the person ate.
    found = dispatch(agent_ctx, "product_search", {"q": "Oat drink barista"})
    assert isinstance(found, dict) and found["products"] == []

    # 2. Register it from the label. Without approve this files a proposal, not a product.
    created = dispatch(
        agent_ctx,
        "product_create",
        {
            "name": "Oat drink barista",
            "brand": "Example Dairy",
            "kcal": 59,
            "protein": 1.3,
            "carbs": 6.9,
            "fat": 3.0,
            "fiber": 0.8,
            "salt": 0.1,
            "reference_unit": "ml",
            "source": "carton label",
            "portions": [
                {"unit_code": "cup", "amount": 200.0, "amount_unit": "ml", "is_default": True}
            ],
            "rationale": "Read from the carton in the capture photo.",
        },
    )
    assert isinstance(created, dict)
    assert created["pending_review"] is True and created["status"] == "pending"
    consumable_id = created["log_against_consumable_id"]
    assert consumable_id is not None
    assert dispatch(agent_ctx, "product_search", {"q": "Oat drink"})["products"] == []  # type: ignore[index]

    # 3. The day is drafted against the pending one-off, so its macros are right today.
    # `manual`: a run for a named day, not one driven by open captures
    run = dispatch(agent_ctx, "agent_run_start", {"mode": "manual", "dates": [DAY.isoformat()]})
    assert isinstance(run, dict) and run["locked_days"] == [DAY.isoformat()]
    run_ctx = dataclasses.replace(agent_ctx, run_id=run["run_id"])
    draft: dict[str, Any] = {
        "run_id": run["run_id"],
        "date": DAY.isoformat(),
        "source_captures": [],
        "training": "rest",
        "meals": [
            {
                "name": "Breakfast",
                "time": "08:30",
                "line_items": [
                    {
                        "raw_text": "a cup of the oat barista drink",
                        "candidates": [],
                        "chosen_consumable_id": consumable_id,
                        "quantity": 200,
                        "unit_code": "ml",
                        "estimated": False,
                        "quantity_estimated": False,
                        "confidence": 0.9,
                        "rationale": "Values from the carton label filed with the proposal.",
                        "source_kind": "text",
                        "source_capture_id": "cap_test",
                    }
                ],
            }
        ],
    }
    written = dispatch(run_ctx, "draft_create", draft)
    assert isinstance(written, dict) and written["created_items"] == 1
    item = written["day"]["meals"][0]["line_items"][0]
    assert item["is_draft"] is True and item["kcal"] == pytest.approx(118.0)
    dispatch(run_ctx, "agent_run_finish", {"run_id": run["run_id"], "summary": "one item"})

    # 4. The agent cannot wave any of it through.
    with pytest.raises(ToolError) as refused:
        dispatch(agent_ctx, "day_approve", {"date": DAY.isoformat(), "close": False})
    assert "approve" in str(refused.value)

    # 5. The person approves the product; the one-off becomes the catalogue entry in place.
    proposal = prop_uc.ListProposals(factory, alice).execute()[0]
    assert proposal.kind == "new" and proposal.consumable_id == consumable_id
    prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)

    promoted = dispatch(tool_ctx, "product_search", {"q": "Oat drink barista"})
    assert isinstance(promoted, dict)
    assert promoted["products"][0]["id"] == consumable_id
    assert promoted["products"][0]["portions"][0]["unit_code"] == "cup"

    # 6. The day still shows the very same item, now approvable as usual.
    approved = dispatch(tool_ctx, "day_approve", {"date": DAY.isoformat(), "close": False})
    assert isinstance(approved, dict)
    kept = approved["meals"][0]["line_items"][0]
    assert kept["id"] == item["id"] and kept["consumable_id"] == consumable_id
    assert kept["is_draft"] is False and kept["kcal"] == pytest.approx(118.0)
