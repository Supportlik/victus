"""T-SVC-055/056: accepting a single drafted item, and the day leaving draft status."""

from __future__ import annotations

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import Conflict
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as days_uc
from victus.application.use_cases import drafts as uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage


def _drafted_day(factory: UowFactory, alice: TenantContext, skyr: int) -> tuple[str, list[int]]:
    """A run that drafts two items on DAY from one capture; returns (capture id, item ids)."""
    cap = capture_uc.UploadCapture(factory, alice, InMemoryBlobStorage()).execute(
        capture_uc.UploadInput(text="a tub of skyr and another one", target_date=DAY)
    )
    start = agent_uc.BeginAgentRun(factory, alice).execute(runner="external", dates=[DAY])
    run_id = start.run.id
    item = {
        "raw_text": "a tub of skyr",
        "candidates": [],
        "chosen_consumable_id": skyr,
        "quantity": 400,
        "unit_code": "g",
        "estimated": False,
        "quantity_estimated": False,
        "confidence": 0.9,
        "rationale": "whole tub",
        "source_kind": "text",
        "source_capture_id": cap.id,
    }
    agent_uc.CreateDraft(factory, alice).execute(
        {
            "run_id": run_id,
            "date": DAY.isoformat(),
            "source_captures": [cap.id],
            "meals": [{"name": "Breakfast", "line_items": [item, {**item, "quantity": 200}]}],
        }
    )
    agent_uc.FinishAgentRun(factory, alice).execute(run_id)
    day = days_uc.GetDay(factory, alice).execute(DAY)
    return cap.id, [li.id for m in day.meals for li in m.line_items if li.is_draft]


def test_single_item_keeps_the_rest_a_draft(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    capture_id, items = _drafted_day(factory, alice, skyr)
    assert len(items) == 2
    view = uc.ApproveLineItem(factory, alice).execute(
        items[0], uc.DraftCorrection(items[0], amount=300)
    )
    assert view.is_draft is False and view.amount == 300
    day = days_uc.GetDay(factory, alice).execute(DAY)
    assert day.has_drafts is True and day.status == "draft"
    # the capture is still open for review while its second item waits
    assert capture_uc.GetCapture(factory, alice).execute(capture_id).status == "assigned"

    with pytest.raises(Conflict):
        uc.ApproveLineItem(factory, alice).execute(items[0])

    uc.ApproveLineItem(factory, alice).execute(items[1])
    day = days_uc.GetDay(factory, alice).execute(DAY)
    assert day.has_drafts is False and day.status == "open" and day.reliable is True
    assert capture_uc.GetCapture(factory, alice).execute(capture_id).status == "processed"


def test_line_items_carry_their_source_and_category(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    capture_id, items = _drafted_day(factory, alice, skyr)
    day = days_uc.GetDay(factory, alice).execute(DAY)
    item = next(li for m in day.meals for li in m.line_items if li.id == items[0])
    assert item.source_capture_id == capture_id and item.source_kind == "text"
    # the fixture product has no category; the field exists so the UI can pick an icon
    assert item.category is None


def test_reassigning_a_consumable_drops_the_old_products_portion(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """A portion belongs to one product; a re-assignment must not keep the old one."""
    from victus.application.use_cases import products as products_uc

    other = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Skyr vanilla", kcal=70, protein=10)
    )
    products_uc.AddPortion(factory, alice).execute(
        other.id,
        products_uc.PortionInput(unit_code="tub", label="tub", amount=450, is_default=True),
    )
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal_id = days_uc.AddMeal(factory, alice).execute(DAY, "Breakfast").id
    item = days_uc.AddLineItem(factory, alice).execute(
        meal_id, days_uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="tub")
    )
    assert item.base_amount == 400

    moved = days_uc.UpdateLineItem(factory, alice).execute(
        item.id, {"consumable_id": other.id, "amount": 1, "unit_code": "tub"}
    )
    assert moved.consumable_id == other.id and moved.base_amount == 450
