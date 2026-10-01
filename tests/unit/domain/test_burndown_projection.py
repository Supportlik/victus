"""T-DOM-100 … T-DOM-105: the burndown carries today's remaining amount forward per trend."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.model.reporting import Stage, TrendRow
from victus.domain.services.burndown import burndown, projections
from victus.domain.services.forecast import ETA_MIN_SLOPE, eta, forecast
from victus.domain.services.trend import moving_average, trend_windows

pytestmark = pytest.mark.domain

TODAY = date(2026, 6, 1)
GOAL = date(2026, 9, 1)  # 92 days after TODAY


def _trend(window: int, slope: float | None) -> TrendRow:
    return TrendRow(
        window=window,
        slope_per_day=slope,
        kg_per_week=round(slope * 7, 2) if slope is not None else None,
        actual_delta=None,
        start=TODAY - timedelta(days=window - 1),
        end=TODAY,
        points=window,
        measured_days=window,
    )


def test_falling_trend_reaches_zero_on_the_forecast_day() -> None:
    """T-DOM-100: a falling slope crosses zero after remaining / -slope days, truncated."""
    [row] = projections([_trend(14, -0.07)], 6.0, TODAY, GOAL, [], horizon=None)
    assert row.window == 14
    assert row.kg_per_week == pytest.approx(-0.49)
    assert row.slope_per_day == pytest.approx(-0.07)
    # 6.0 / 0.07 = 85.7 days → 85, like forecast.forecast
    assert row.crossing == TODAY + timedelta(days=85)
    assert row.crossing == eta(6.0, -0.07, TODAY)
    assert row.path == [(TODAY, 6.0), (TODAY + timedelta(days=85), 0.0)]


@pytest.mark.parametrize("slope", [0.0, ETA_MIN_SLOPE, 0.0005, 0.04, None])
def test_flat_rising_or_unknown_trend_never_crosses(slope: float | None) -> None:
    """T-DOM-101: slope ≥ ETA_MIN_SLOPE (or none at all) is "not at this pace": no date, no line."""
    [row] = projections([_trend(7, slope)], 6.0, TODAY, GOAL, [Stage("Target", GOAL)], None)
    assert row.crossing is None
    assert row.days_vs_goal is None
    assert row.stages == []
    assert row.path == []


@pytest.mark.parametrize(
    ("slope", "expected_days"),
    [
        (-0.1, -32),  # 6.0 / 0.1 = 60 days → 32 days before the goal date
        (-6.0 / 92, 0),  # exactly on the goal date
        (-0.05, 28),  # 120 days → 28 days late
    ],
)
def test_crossing_before_on_and_after_the_goal_date(slope: float, expected_days: int) -> None:
    """T-DOM-102: the difference to the goal date is early (negative), on time (0) or late."""
    stages = [Stage("Stretch", date(2026, 8, 1)), Stage("Target", GOAL)]
    [row] = projections([_trend(30, slope)], 6.0, TODAY, GOAL, stages, None)
    assert row.crossing is not None
    assert row.days_vs_goal == expected_days
    assert row.days_vs_goal == (row.crossing - GOAL).days
    assert [(s.name, s.date) for s in row.stages] == [(s.name, s.date) for s in stages]
    stretch, target = row.stages
    assert stretch.days == (row.crossing - date(2026, 8, 1)).days
    assert target.days == expected_days


def test_line_stops_at_the_horizon_when_zero_lies_beyond_it() -> None:
    """T-DOM-103: a crossing past the horizon keeps its date; the line stops at the horizon."""
    horizon = TODAY + timedelta(days=30)
    [row] = projections([_trend(30, -0.02)], 6.0, TODAY, GOAL, [], horizon=horizon)
    assert row.crossing == TODAY + timedelta(days=300)
    assert row.path[0] == (TODAY, 6.0)
    assert row.path[-1][0] == horizon
    assert row.path[-1][1] == pytest.approx(6.0 - 0.02 * 30)
    # a crossing inside the horizon ends on zero
    [inside] = projections([_trend(7, -0.25)], 6.0, TODAY, GOAL, [], horizon=horizon)
    assert inside.path[-1] == (TODAY + timedelta(days=24), 0.0)


def test_projection_equals_forecast_eta_on_the_reference(ref: Reference) -> None:
    """T-DOM-104: on the frozen reference the crossing is the forecast ETA of the same window."""
    ma = moving_average(ref.daily, ref.ma_days)
    trends = trend_windows(ma, ref.daily, ref.trend_windows, today=ref.today)
    res = burndown(
        ma,
        ref.burndown_start,
        ref.goal_kg,
        ref.goal_date,
        ref.today,
        [Stage(n, d) for n, d in ref.stages],
        ref.kcal_per_kg,
        trends=trends,
    )
    assert res is not None
    fc = forecast(trends, ma[ref.today], ref.today, ref.goal_kg, ref.goal_date)
    expected = {e["tage"]: e["eta"] for e in ref.out["forecast"]}
    assert [p.window for p in res.projections] == ref.trend_windows
    for proj, f in zip(res.projections, fc, strict=True):
        assert proj.crossing == f.eta
        assert (proj.crossing.isoformat() if proj.crossing else None) == expected[proj.window]
        assert proj.kg_per_week == f.kg_per_week
    # the reference has both kinds: 7/14/21 do not reach the goal, 30/60/90 do
    assert [p.crossing is None for p in res.projections] == [True, True, True, False, False, False]


def test_burndown_without_trends_and_with_its_own_as_of() -> None:
    """T-DOM-105: no trends → no projections; the line starts on ``as_of``, not the last MA day."""
    anchor = date(2026, 3, 1)
    today = anchor + timedelta(days=50)
    ma = {anchor + timedelta(days=i): 95.0 - 0.06 * i for i in range(51)}
    plain = burndown(ma, anchor, 85.0, GOAL, today, [Stage("Target", GOAL)], 7716.17)
    assert plain is not None and plain.projections == []
    as_of = today + timedelta(days=2)
    res = burndown(
        ma,
        anchor,
        85.0,
        GOAL,
        today,
        [Stage("Target", GOAL)],
        7716.17,
        trends=[_trend(7, -0.03)],
        as_of=as_of,
    )
    assert res is not None
    [row] = res.projections
    assert row.path[0][0] == as_of
    assert row.path[0][1] == pytest.approx(7.0)
    assert row.crossing == eta(res.remaining_today, -0.03, as_of)
    # the chart's horizon is the goal date here (no later stage), and zero lies beyond it
    assert row.crossing is not None and row.crossing > GOAL
    assert row.path[-1][0] == GOAL
