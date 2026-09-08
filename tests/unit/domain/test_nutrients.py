"""T-DOM-001 / T-DOM-025: nutrient arithmetic — frozen quantities, propagating nutrients."""

import pytest

from victus.domain.services.nutrients import (
    batch_per_100,
    day_totals,
    line_item_macros,
    macros_per_100,
    sum_macros,
)
from victus.domain.values import Macros

pytestmark = pytest.mark.domain

PER100 = Macros(kcal=157, protein=7.6, carbs=20.0, fat=4.4, fiber=2.4, salt=1.0)


def test_line_item_macros_scales_by_base_quantity() -> None:
    m = line_item_macros(PER100, 300)
    assert m.kcal == pytest.approx(471)
    assert m.protein == pytest.approx(22.8)
    assert m.salt == pytest.approx(3.0)


def test_undeclared_macro_stays_none() -> None:
    m = line_item_macros(Macros(kcal=100), 50)
    assert m.kcal == 50
    assert m.salt is None


def test_macros_per_100_from_other_reference_amount() -> None:
    per_serving = Macros(kcal=471, protein=22.8)  # declared per 300 g pack
    assert macros_per_100(per_serving, 300).kcal == pytest.approx(157)
    assert macros_per_100(PER100, 100) is PER100


def test_batch_per_100() -> None:
    totals = Macros(kcal=2400, protein=180)
    per = batch_per_100(totals, 1200)
    assert per.kcal == 200
    assert per.protein == 15
    assert batch_per_100(totals, None).kcal is None


def test_sum_and_day_totals_rounding() -> None:
    items = [Macros(kcal=252.4, protein=44.0, salt=0.36), Macros(kcal=419.9, protein=67.32)]
    s = sum_macros(items)
    assert s.kcal == pytest.approx(672.3)
    assert s.salt == pytest.approx(0.36)  # declared on one item only → counted
    assert s.carbs is None  # declared nowhere → undeclared
    t = day_totals(items)
    assert t.kcal == 672
    assert t.protein == 111.3
    assert t.salt == 0.36


def test_frozen_quantity_propagating_nutrients() -> None:
    """T-DOM-025: correcting a product label changes the item's kcal, not its quantity."""
    base_quantity = 396.0
    before = line_item_macros(Macros(kcal=120, protein=22), base_quantity)
    after = line_item_macros(Macros(kcal=106, protein=17), base_quantity)
    assert before.kcal == pytest.approx(475.2)
    assert after.kcal == pytest.approx(419.76)
    assert base_quantity == 396.0


def test_negative_quantity_rejected() -> None:
    with pytest.raises(ValueError):
        line_item_macros(PER100, -1)
