"""T-SVC-425…431, 439: day, meal, line item and draft use cases at their edges."""

from __future__ import annotations

from datetime import date, timedelta
from datetime import time as dt_time
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE, TenantContext
from victus.application.use_cases import day_logs as uc
from victus.application.use_cases import drafts as drafts_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db import orm

pytestmark = pytest.mark.service

DAY = date(2026, 3, 10)

SETTINGS: dict[str, Any] = {
    "goal": {"weight_kg": 80, "date": "2027-01-31"},
    "kcal_per_kg": 7716.17,
    "calorie_corridor": {"min": 1400, "max": 2000, "asymmetric": True},
    "target_bands": [
        {
            "name": "Rest day",
            "training_type": "rest",
            "valid_from": "2026-01-01",
            "protein": {"min": 105, "opt_min": 150, "opt_max": 185, "target": 165, "max": 200},
            "carbs": {"min": 120, "opt_min": 155, "opt_max": 200, "target": 180, "max": 230},
            "fat": {"min": 45, "opt_min": 55, "opt_max": 70, "target": 58, "max": 75},
            "fiber": {"min": 25, "opt_min": 32, "opt_max": 38, "target": 35, "max": 50},
            "salt": {"min": 4, "opt_min": 6, "opt_max": 8, "target": 8, "max": 15},
        }
    ],
}


@pytest.fixture
def writer(alice: TenantContext) -> TenantContext:
    """May write, may not approve: what it logs arrives as a draft (R81)."""
    return TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_w", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
    )


def _meal(factory: UowFactory, ctx: TenantContext, day: date = DAY, name: str = "Breakfast") -> int:
    if not _exists(factory, ctx, day):
        uc.CreateDay(factory, ctx).execute(day, reliable=True)
    return uc.AddMeal(factory, ctx).execute(day, name).id


def _exists(factory: UowFactory, ctx: TenantContext, day: date) -> bool:
    with factory(ctx) as uow:
        return uow.day_logs.get_by_date(day) is not None


def _item(factory: UowFactory, ctx: TenantContext, meal: int, product: int, grams: float) -> int:
    return (
        uc.AddLineItem(factory, ctx)
        .execute(meal, uc.LineItemInput(consumable_id=product, amount=grams, unit_code="g"))
        .id
    )


def test_t_svc_425_day_input_guards(factory: UowFactory, alice: TenantContext, skyr: int) -> None:
    """T-SVC-425: an unknown training type, a reversed range, a twin day, a blank meal name,
    a negative amount, an unknown unit, an unknown portion and a blank message are refused."""
    with pytest.raises(ValidationFailed, match="unknown training_type"):
        uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="yoga")
    with pytest.raises(ValidationFailed, match="before from"):
        uc.ListDays(factory, alice).execute(DAY, DAY - timedelta(days=1))
    meal = _meal(factory, alice)
    with pytest.raises(Conflict, match="exists"):
        uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    with pytest.raises(ValidationFailed, match="must not be empty"):
        uc.UpdateMeal(factory, alice).execute(meal, {"name": "  "})
    for item, err, match in (
        (uc.LineItemInput(skyr, -1, "g"), ValidationFailed, "zero or positive"),
        (uc.LineItemInput(skyr, 1, "bucket"), ValidationFailed, "unknown unit"),
        (uc.LineItemInput(skyr, 1, "tub", portion_id=999_999), NotFound, "portion 999999"),
    ):
        with pytest.raises(err, match=match):
            uc.AddLineItem(factory, alice).execute(meal, item)
    with pytest.raises(ValidationFailed, match="text is required"):
        uc.AddDayMessage(factory, alice).execute(DAY, "   ")


def test_t_svc_426_flags_meal_time_and_item_flags(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-426: training type and notes change without touching reliability; a meal's time
    alone changes; a drafted item's estimate flags change without ``approve``; re-assigning
    it to a consumable that does not exist is 404."""
    meal = _meal(factory, alice)
    day = uc.UpdateDayFlags(factory, alice).execute(
        DAY, {"training_type": "strength", "notes": "legs"}
    )
    assert day.training_type == "strength" and day.reliable is True
    m = uc.UpdateMeal(factory, alice).execute(meal, {"time": None})
    assert m.time is None
    draft = _item(factory, writer, meal, skyr, 150)
    changed = uc.UpdateLineItem(factory, writer).execute(
        draft, {"estimated": True, "amount_estimated": None}
    )
    assert changed.estimated is True
    with pytest.raises(NotFound, match="consumable"):
        uc.UpdateLineItem(factory, writer).execute(draft, {"consumable_id": 999_999})


def test_t_svc_427_close_refuses_drafts_and_keeps_a_frozen_band(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-427: a day with a drafted item cannot be closed; once it is clean, closing,
    reopening and closing again keeps the band frozen the first time."""
    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    meal = uc.AddMeal(factory, alice).execute(DAY, "Lunch").id
    draft = _item(factory, writer, meal, skyr, 100)
    with pytest.raises(Conflict, match="draft items"):
        uc.CloseDay(factory, alice).execute(DAY)
    drafts_uc.ApproveLineItem(factory, alice).execute(draft)
    first = uc.CloseDay(factory, alice).execute(DAY)
    assert first.target_band is not None
    uc.ReopenDay(factory, alice).execute(DAY)
    again = uc.CloseDay(factory, alice).execute(DAY)
    assert again.target_band == first.target_band


def test_t_svc_428_a_band_with_a_missing_bound_gives_no_zones(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-SVC-428: a stored band that lacks a bound is shown with zeros for that macro and
    yields no zones, rather than a zone computed against a missing number."""
    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    with session_factory() as s:
        band = s.query(orm.TargetBand).filter_by(tenant_id=alice.tenant_id).one()
        band.protein_min = None
        s.commit()
    uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    view = uc.GetDay(factory, alice).execute(DAY)
    assert view.target_band is not None
    assert view.target_band.protein.min == 0
    assert view.zones == {}


def test_t_svc_429_approving_items_with_corrections(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-429: an item is moved to a meal by id or to an existing one by name; an unknown
    meal is 404; a delete is not a correction here; a day correction may swap the product
    and names a foreign item or an unknown product as 404."""
    breakfast = _meal(factory, alice)
    lunch = uc.AddMeal(factory, alice).execute(DAY, "Lunch").id
    oats = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Oats", kcal=370, protein=13, carbs=59, fat=7, fiber=10, salt=0
        )
    )
    a, b, c = (_item(factory, writer, breakfast, skyr, g) for g in (100, 120, 140))
    moved = drafts_uc.ApproveLineItem(factory, alice).execute(a, meal_id=lunch)
    assert moved.meal_id == lunch
    by_name = drafts_uc.ApproveLineItem(factory, alice).execute(b, meal_name=" lunch ")
    assert by_name.meal_id == lunch
    with pytest.raises(NotFound, match="meal 999999"):
        drafts_uc.ApproveLineItem(factory, alice).execute(c, meal_id=999_999)
    with pytest.raises(ValidationFailed, match="DELETE"):
        drafts_uc.ApproveLineItem(factory, alice).execute(
            c, drafts_uc.DraftCorrection(line_item_id=c, delete=True)
        )

    with pytest.raises(NotFound, match="not part of"):
        drafts_uc.ApproveDay(factory, alice).execute(
            DAY, [drafts_uc.DraftCorrection(line_item_id=999_999, amount=1)], close=False
        )
    with pytest.raises(NotFound, match="consumable 999999"):
        drafts_uc.ApproveDay(factory, alice).execute(
            DAY, [drafts_uc.DraftCorrection(line_item_id=c, consumable_id=999_999)], close=False
        )
    day = drafts_uc.ApproveDay(factory, alice).execute(
        DAY, [drafts_uc.DraftCorrection(line_item_id=c, consumable_id=oats.id)], close=False
    )
    swapped = [li for m in day.meals for li in m.line_items if li.id == c]
    assert swapped[0].consumable_id == oats.id


def test_t_svc_430_discard_edges(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    session_factory: sessionmaker[Session],
) -> None:
    """T-SVC-430: discarding an unknown day is 404, a day without drafts says so, and a
    drafted day that keeps approved items becomes an ordinary open day."""
    with pytest.raises(NotFound):
        drafts_uc.DiscardDraft(factory, alice).execute(DAY)
    meal = _meal(factory, alice)
    _item(factory, alice, meal, skyr, 100)  # approved
    with pytest.raises(ValidationFailed, match="nothing to discard"):
        drafts_uc.DiscardDraft(factory, alice).execute(DAY)
    _item(factory, writer, meal, skyr, 50)  # drafted
    with session_factory() as s:
        row = s.query(orm.DayLog).filter_by(tenant_id=alice.tenant_id, date=DAY).one()
        row.status = "draft"
        s.commit()
    assert drafts_uc.DiscardDraft(factory, alice).execute(DAY) == 1
    assert uc.GetDay(factory, alice).execute(DAY).status == "open"


def test_t_svc_431_summary_shows_portions_and_missing_numbers(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-431: the draft summary names the portion an item was logged in, and a day
    without values prints a dash instead of a number."""
    meal = _meal(factory, alice)
    big = products_uc.AddPortion(factory, alice).execute(
        skyr, products_uc.PortionInput("tub", "large tub", 1000)
    )
    uc.AddLineItem(factory, writer).execute(
        meal, uc.LineItemInput(skyr, 1, "tub", portion_id=big.id)
    )
    md = drafts_uc.DraftSummary(factory, alice).execute(DAY).markdown
    assert "1.0 tub (large tub)" in md
    assert drafts_uc._fmt(None) == "–"


def test_t_svc_439_a_rename_alone_keeps_the_time(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-439: renaming a meal without a ``time`` key leaves its time as it was."""
    uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = uc.AddMeal(factory, alice).execute(DAY, "Breakfast", dt_time(7, 30))
    renamed = uc.UpdateMeal(factory, alice).execute(meal.id, {"name": "Brunch"})
    assert renamed.name == "Brunch" and renamed.time == dt_time(7, 30)
