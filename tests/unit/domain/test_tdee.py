"""T-DOM-003 / T-DOM-004 / T-DOM-026: weekly and rolling TDEE, implied TDEE, required rate."""

from datetime import date, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.services.tdee import (
    eat_target,
    implied_tdee,
    reference_tdee,
    required_rate,
    rolling_tdee,
    weekly_tdee,
)
from victus.domain.services.trend import moving_average
from victus.domain.values import CalorieCorridor, Quality

pytestmark = pytest.mark.domain


def test_weekly_tdee_hand_example() -> None:
    """Two full weeks: −0.5 kg at 2000 kcal/day (7 logged days) → raw = 2000 + 0.5·7716.17/7."""
    mon = date(2026, 1, 5)
    daily = {mon + timedelta(days=i): 90.0 for i in range(7)}
    daily.update({mon + timedelta(days=7 + i): 89.5 for i in range(7)})
    cals = {mon + timedelta(days=i): 2000.0 for i in range(14)}
    rows = weekly_tdee(daily, cals, 7716.17)
    assert rows[0].tdee is None  # no previous week → no delta
    assert rows[1].delta_kg == -0.5
    assert rows[1].tdee == round(2000 + 0.5 * 7716.17 / 7)  # 2551, first tdee is not smoothed


def test_weekly_tdee_matches_reference(ref: Reference) -> None:
    rows = weekly_tdee(ref.daily, ref.calories, ref.kcal_per_kg)
    for row, exp in zip(rows, ref.out["weekly"], strict=True):
        assert row.week_start == date.fromisoformat(exp["woche"])
        assert row.mean_kg == exp["gewicht"]
        assert row.delta_kg == exp["delta"]
        assert row.days_with_kcal == exp["n_kcal"]
        assert row.tdee == exp["tdee"]


def test_rolling_tdee_matches_reference(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    corridor = CalorieCorridor(*ref.corridor)
    rows = rolling_tdee(
        ref.daily, ma, ref.calories, ref.protein, ref.windows, ref.kcal_per_kg, corridor
    )
    assert [r.window_days for r in rows] == ref.windows
    for row in rows:
        exp = ref.out["rolling"][str(row.window_days)]
        assert row.mean_kcal == exp["kcal"]
        assert row.delta_ma_kg == exp["delta"]
        assert row.coverage_pct == exp["abdeckung"]
        assert row.days_with_kcal == exp["n_kcal"]
        assert row.measured_days == exp["messtage"]
        assert row.days_without_macros == exp["ohne_makros"]
        assert row.in_corridor == exp["im_korridor"]
        assert row.above_corridor == exp["ueber"]
        assert row.below_corridor == exp["unter"]
        assert row.mean_protein == exp["eiweiss"]
        if exp["tdee"] is None:
            assert row.tdee is None
        else:
            assert row.tdee == pytest.approx(exp["tdee"], abs=1)
        if exp.get("quality"):
            assert row.quality is Quality(exp["quality"])


def test_rolling_divides_by_calendar_days_not_logged_days() -> None:
    """Untracked days count as the tracked mean — only the calendar-day divisor does that."""
    end = date(2026, 3, 31)
    daily = {end - timedelta(days=i): 90.0 + 0.1 * i for i in range(15)}  # −0.1 kg/day
    ma = moving_average(daily, 1)  # MA of 1 day = raw
    cals = {end - timedelta(days=i): 2000.0 for i in range(14) if i % 2 == 0}  # every other day
    rows = rolling_tdee(daily, ma, cals, {}, [14], 7716.17, CalorieCorridor(1400, 2000))
    r = rows[0]
    assert r.coverage_pct == 50
    assert r.tdee == round(2000 + 1.4 * 7716.17 / 14)  # delta over 14 calendar days = −1.4 kg
    assert r.quality is Quality.YELLOW


def test_reference_tdee_prefers_rolling_14(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    weeks = weekly_tdee(ref.daily, ref.calories, ref.kcal_per_kg)
    rolling = rolling_tdee(
        ref.daily,
        ma,
        ref.calories,
        ref.protein,
        ref.windows,
        ref.kcal_per_kg,
        CalorieCorridor(*ref.corridor),
    )
    value, basis = reference_tdee(weeks, rolling)
    assert basis == "rolling_14d"
    assert value == ref.out["rolling"]["14"]["tdee"]
    assert reference_tdee(weeks, [])[1] == "weekly_mean_8w"
    assert reference_tdee([], []) == (None, "none")


def test_implied_tdee_and_required_rate() -> None:
    """T-DOM-026: predecessor status.py arithmetic."""
    w = {date(2026, 1, 1): 90.0, date(2026, 1, 14): 89.0}
    assert implied_tdee(w, [2000.0] * 10, 7716.17) == pytest.approx(2000 + 7716.17 / 10)
    assert implied_tdee({date(2026, 1, 1): 90.0}, [2000.0], 7716.17) is None
    rr = required_rate(90.0, 85.0, date(2026, 1, 1) + timedelta(days=70), date(2026, 1, 1), 7716.17)
    assert rr.days_left == 70
    assert rr.kg_per_week == pytest.approx(-0.5)
    assert rr.deficit_kcal_per_day == pytest.approx(5 / 70 * 7716.17)
    assert rr.to_go_kg == 5.0
    assert eat_target(2600, rr) == round(2600 - 5 / 70 * 7716.17)
    assert eat_target(None, rr) is None
