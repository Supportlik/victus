"""T-DOM-206…214: domain service edges — matching, bands, TDEE, trend, units, burndown."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from victus.domain.model.checks import Tolerances
from victus.domain.model.reporting import BandStat, Stage
from victus.domain.services import burndown as bd
from victus.domain.services.matching import ConsumableIndex, coverage
from victus.domain.services.nutrients import macros_per_100
from victus.domain.services.target_band import select_band, training_type_from_text
from victus.domain.services.tdee import rolling_tdee, rolling_window, weekly_tdee
from victus.domain.services.trend import (
    moving_average,
    regression_slope,
    slope_for_window,
    trend_windows,
)
from victus.domain.services.units import base_factor
from victus.domain.values import (
    Band,
    BandZone,
    CalorieCorridor,
    ConsumableKind,
    Macros,
    Message,
    TargetBand,
    TrainingType,
)

pytestmark = pytest.mark.domain

D0 = date(2026, 1, 5)  # a Monday
CORRIDOR = CalorieCorridor(1400, 2000)


def test_matching_edges() -> None:
    """T-DOM-206: empty strings score 0, parenthesis-only names have no short form,
    and a product wins when no recipe qualifies."""
    assert coverage("", "oats") == 0.0
    assert coverage("oats", "") == 0.0

    index = ConsumableIndex(
        [
            (1, ConsumableKind.PRODUCT, "(raw)"),  # short form is empty
            (2, ConsumableKind.PRODUCT, "Rolled oats"),
            (3, "recipe_batch", "Oat porridge with berries"),
        ]
    )
    assert len(index) == 3
    # the parenthesis-only entry is found by its full form only
    assert [c.consumable_id for c in index.find("(raw)")] == [1]
    # an input with nothing outside parentheses has an empty short form: no fuzzy hit
    assert index.find("(barley flakes)") == []
    best = index.best("rolled oats")
    assert best is not None and best.consumable_id == 2
    assert best.kind is ConsumableKind.PRODUCT
    assert index.best("") is None


def test_macros_per_100_rejects_a_non_positive_reference() -> None:
    """T-DOM-207: a declaration per 0 g cannot be normalised."""
    with pytest.raises(ValueError, match="positive"):
        macros_per_100(Macros(kcal=100.0), 0)
    assert macros_per_100(Macros(kcal=50.0), 50).kcal == 100.0


def _profile(tt: TrainingType | None, valid_from: date = D0) -> TargetBand:
    b = Band(min=1, opt_min=2, opt_max=3, target=2.5, max=4)
    return TargetBand("p", tt, valid_from, None, protein=b, carbs=b, fat=b, fiber=b, salt=b)


def test_target_band_fallbacks() -> None:
    """T-DOM-208: a bare "yes" names no type; with no preferred profile the newest valid wins."""
    assert training_type_from_text("yes") is None
    assert training_type_from_text("Training") is None
    older = _profile(TrainingType.STRENGTH)
    later = replace(older, name="later", valid_from=D0 + timedelta(days=3))
    # asked for martial arts; no exact, no generic, no rest profile → newest valid one
    hit = select_band([older, later], D0 + timedelta(days=5), TrainingType.MARTIAL_ARTS)
    assert hit is later


def test_weekly_tdee_discards_an_implausible_week() -> None:
    """T-DOM-209: a 10 kg drop in one week gives a TDEE above 6000 kcal, which is dropped."""
    daily = {D0 + timedelta(days=i): 90.0 for i in range(7)}
    daily.update({D0 + timedelta(days=7 + i): 80.0 for i in range(7)})
    cals = {D0 + timedelta(days=i): 2000.0 for i in range(14)}
    rows = weekly_tdee(daily, cals, 7716.17)
    assert rows[1].delta_kg == -10.0
    assert rows[1].tdee is None

    # a week with intake but no weigh-in has no mean weight and keeps the previous one
    cals[D0 + timedelta(days=14)] = 2000.0
    daily[D0 + timedelta(days=21)] = 79.5
    rows = weekly_tdee(daily, cals, 7716.17)
    assert rows[2].mean_kg is None and rows[2].delta_kg is None
    assert rows[3].delta_kg == -0.5, "the delta is taken against the last week with weight"


def test_rolling_tdee_without_data() -> None:
    """T-DOM-210: no moving average → no window; no logged kcal → a window without TDEE."""
    assert rolling_window({}, {}, {}, {}, 7, 7716.17, CORRIDOR) is None
    assert rolling_tdee({}, {}, {}, {}, [7, 14], 7716.17, CORRIDOR) == []

    daily = {D0 + timedelta(days=i): 90.0 - 0.1 * i for i in range(10)}
    ma = moving_average(daily, 7)
    [row] = rolling_tdee(daily, ma, {}, {}, [7], 7716.17, CORRIDOR)
    assert row.mean_kcal is None
    assert row.tdee is None and row.rejected_tdee is None and row.quality is None
    assert row.coverage_pct == 0


def test_trend_edges() -> None:
    """T-DOM-211: a zero-width average raises, no spread gives no slope, no data no rows."""
    with pytest.raises(ValueError, match="n must be"):
        moving_average({D0: 90.0}, 0)
    same_day = [(D0, 90.0), (D0, 91.0), (D0, 92.0)]
    assert regression_slope(same_day) is None
    assert slope_for_window({}, 7) == (None, 0)
    assert trend_windows({}, {}, [7, 14]) == []


def test_base_factor_of_a_count_unit_is_none() -> None:
    """T-DOM-212: a piece has no mass of its own, and an unknown code no factor."""
    assert base_factor("piece") is None
    assert base_factor("no-such-unit") is None
    assert base_factor("kg") == (1000.0, "g")


def test_burndown_edges() -> None:
    """T-DOM-213: no anchor or no MA on today → None; stages outside the range are skipped."""
    ma = {D0 + timedelta(days=i): 90.0 - 0.1 * i for i in range(20)}
    today = D0 + timedelta(days=19)
    goal = D0 + timedelta(days=200)
    assert bd.burndown(ma, D0 + timedelta(days=30), 80.0, goal, today, [], 7716.17) is None
    assert bd.burndown(ma, D0, 80.0, goal, today + timedelta(days=1), [], 7716.17) is None
    stages = [
        Stage("before anchor", D0 - timedelta(days=1)),
        Stage("inside", D0 + timedelta(days=100)),
        Stage("after end", D0 + timedelta(days=150)),
    ]
    result = bd.burndown(ma, D0, 80.0, goal, today, stages, 7716.17, end=D0 + timedelta(days=120))
    assert result is not None
    assert [s.name for s in result.stages] == ["inside"]


def test_small_value_helpers() -> None:
    """T-DOM-214: Macros.zero, per-macro tolerances and BandStat.zone_counts."""
    zero = Macros.zero()
    assert set(zero.as_dict().values()) == {0.0}
    profile = _profile(None)
    assert profile.band_for("protein") is profile.protein
    assert profile.band_for("kcal") is None
    assert Message("{n} days left, {m} logged", {"n": 3, "m": 2}).fill() == "3 days left, 2 logged"
    assert Message("no basis yet").fill() == "no basis yet"
    tol = Tolerances()
    assert tol.for_macro("kcal") == 3.0
    assert tol.for_macro("salt") == 0.06
    assert tol.for_macro("protein") == 0.6
    stat = BandStat(
        below_min=1, below_optimum=2, optimal=3, above_optimum=4, above_max=5, mean=2.0, n=15
    )
    assert stat.zone_counts() == {
        BandZone.BELOW_MIN: 1,
        BandZone.BELOW_OPTIMUM: 2,
        BandZone.OPTIMAL: 3,
        BandZone.ABOVE_OPTIMUM: 4,
        BandZone.ABOVE_MAX: 5,
    }
