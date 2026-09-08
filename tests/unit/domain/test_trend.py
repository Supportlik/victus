"""T-DOM-006 / T-DOM-007 / T-DOM-010: moving average, regression trends, yearly stats."""

from datetime import date, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.services.trend import (
    moving_average,
    regression_slope,
    trend_windows,
    yearly_stats,
)

pytestmark = pytest.mark.domain


def test_moving_average_hand_example() -> None:
    d0 = date(2026, 1, 1)
    series = {d0: 100.0, d0 + timedelta(days=1): 102.0, d0 + timedelta(days=3): 98.0}
    ma = moving_average(series, 3)
    assert ma[d0] == 100.0
    assert ma[d0 + timedelta(days=1)] == 101.0
    # window 3 days back from Jan 4 covers Jan 2–4 → only Jan 2 (102) and Jan 4 (98)
    assert ma[d0 + timedelta(days=3)] == 100.0


def test_moving_average_matches_reference(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    exp = {date.fromisoformat(k): v for k, v in ref.out["moving_average"].items()}
    assert ma.keys() == exp.keys()
    for d, v in exp.items():
        assert ma[d] == pytest.approx(v, abs=0.01), d


def test_regression_slope_hand_example() -> None:
    d0 = date(2026, 1, 1)
    pts = [(d0 + timedelta(days=i), 100.0 - 0.1 * i) for i in range(5)]
    assert regression_slope(pts) == pytest.approx(-0.1)
    assert regression_slope(pts[:2]) is None


def test_trend_windows_match_reference(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    rows = trend_windows(ma, ref.daily, ref.trend_windows, ref.today)
    for row, exp in zip(rows, ref.out["trends"], strict=True):
        assert row.window == exp["tage"]
        if exp["slope"] is None:
            assert row.slope_per_day is None
        else:
            assert row.slope_per_day == pytest.approx(exp["slope"], abs=0.0005)
            assert row.kg_per_week == pytest.approx(exp["rate"], abs=0.01)
        assert row.actual_delta == pytest.approx(exp["diff"], abs=0.01)
        assert row.points == exp["punkte"]
        assert row.measured_days == exp["messtage"]


def test_yearly_stats_matches_reference(ref: Reference) -> None:
    rows = yearly_stats(ref.daily)
    for row, exp in zip(rows, ref.out["years"], strict=True):
        assert row.year == exp["jahr"]
        assert row.start == exp["start"] and row.end == exp["ende"]
        assert row.delta == pytest.approx(exp["delta"], abs=0.01)
        assert row.min == exp["min"] and row.max == exp["max"]
        assert row.mean == pytest.approx(exp["schnitt"], abs=0.01)
        assert row.measured_days == exp["messtage"]


def test_yearly_stats_single_point_year() -> None:
    rows = yearly_stats({date(2024, 5, 1): 90.0})
    assert rows[0].delta is None and rows[0].measured_days == 1
