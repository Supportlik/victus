"""T-DOM-008: forecast horizons and ETA."""

from datetime import date, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.model.reporting import TrendRow
from victus.domain.services.forecast import forecast
from victus.domain.services.trend import moving_average, trend_windows

pytestmark = pytest.mark.domain


def _row(window: int, slope: float | None) -> TrendRow:
    today = date(2026, 6, 1)
    return TrendRow(
        window, slope, None if slope is None else round(slope * 7, 2), None, today, today, 10, 10
    )


def test_forecast_hand_example() -> None:
    today = date(2026, 6, 1)
    rows = forecast([_row(30, -0.1)], 90.0, today, 85.0, today + timedelta(days=100))
    r = rows[0]
    assert r.m1 == pytest.approx(90 - 3.044)
    assert r.m3 == pytest.approx(90 - 9.131)
    assert r.m6 == pytest.approx(90 - 18.262)
    assert r.at_goal_date == pytest.approx(80.0)
    assert r.eta == today + timedelta(days=50)


def test_no_eta_when_flat_or_below_goal() -> None:
    today = date(2026, 6, 1)
    assert forecast([_row(7, -0.0005)], 90.0, today, 85.0, today)[0].eta is None
    assert forecast([_row(7, -0.2)], 84.0, today, 85.0, today)[0].eta is None
    assert forecast([_row(7, None)], 90.0, today, 85.0, today)[0].m1 is None


def test_forecast_matches_reference(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    trends = trend_windows(ma, ref.daily, ref.trend_windows, ref.today)
    rows = forecast(trends, ma[ref.today], ref.today, ref.goal_kg, ref.goal_date)
    for row, exp in zip(rows, ref.out["forecast"], strict=True):
        assert row.window == exp["tage"]
        if "m1" not in exp:
            assert row.m1 is None
            continue
        assert row.m1 == pytest.approx(exp["m1"], abs=0.01)
        assert row.m3 == pytest.approx(exp["m3"], abs=0.01)
        assert row.m6 == pytest.approx(exp["m6"], abs=0.01)
        assert row.at_goal_date == pytest.approx(exp["am_ziel"], abs=0.01)
        assert (row.eta.isoformat() if row.eta else None) == exp["eta"]
