"""T-DOM-009: burndown planned vs. actual, per stage."""

from datetime import date, timedelta
from itertools import pairwise

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.model.reporting import Stage
from victus.domain.services.burndown import burndown, planned_path
from victus.domain.services.trend import moving_average

pytestmark = pytest.mark.domain


def test_planned_path_ends_exactly_at_zero() -> None:
    anchor = date(2026, 3, 1)
    pts = planned_path(anchor, 10.0, anchor + timedelta(days=100), step=3)
    assert pts[0] == (anchor, 10.0)
    assert pts[-1] == (anchor + timedelta(days=100), 0.0)
    assert all(b[1] <= a[1] for a, b in pairwise(pts))


def test_burndown_hand_example() -> None:
    anchor = date(2026, 3, 1)
    today = anchor + timedelta(days=50)
    goal = today + timedelta(days=50)
    ma = {anchor + timedelta(days=i): 95.0 - 0.06 * i for i in range(51)}
    res = burndown(ma, anchor, 85.0, goal, today, [Stage("Target", goal)], 7716.17, tdee_ref=2600)
    assert res is not None
    assert res.remaining_at_anchor == pytest.approx(10.0)
    assert res.remaining_today == pytest.approx(7.0)
    assert res.planned_remaining_today == pytest.approx(5.0)  # half the time → half the kg
    assert res.gap == pytest.approx(-2.0)  # behind plan
    assert res.planned_rate_per_week == pytest.approx(10 / (100 / 7))
    assert res.stages[0].required_kg_per_week == pytest.approx(7 / (50 / 7))
    assert res.stages[0].feasible is True


def test_burndown_none_when_goal_reached() -> None:
    anchor = date(2026, 3, 1)
    ma = {anchor: 84.0, anchor + timedelta(days=1): 84.0}
    assert (
        burndown(
            ma, anchor, 85.0, anchor + timedelta(days=30), anchor + timedelta(days=1), [], 7716.17
        )
        is None
    )


def test_burndown_matches_reference(ref: Reference) -> None:
    ma = moving_average(ref.daily, ref.ma_days)
    stages = [Stage(n, d) for n, d in ref.stages]
    res = burndown(
        ma, ref.burndown_start, ref.goal_kg, ref.goal_date, ref.today, stages, ref.kcal_per_kg
    )
    assert res is not None
    exp = ref.out["burndown"]
    assert res.anchor.isoformat() == exp["anchor"]
    assert res.remaining_at_anchor == pytest.approx(exp["rest0"], abs=0.01)
    assert res.remaining_today == pytest.approx(exp["ist"], abs=0.01)
    assert res.planned_remaining_today == pytest.approx(exp["soll"], abs=0.01)
    assert res.gap == pytest.approx(exp["delta"], abs=0.01)
    assert res.burned == pytest.approx(exp["abgebaut"], abs=0.01)
    assert res.days_elapsed == exp["tage"]
    assert res.actual_rate_per_week == pytest.approx(exp["rate_ist"], abs=0.001)
    assert res.planned_rate_per_week == pytest.approx(exp["rate_soll"], abs=0.001)
    assert res.required_rate_per_week == pytest.approx(exp["rate_noetig"], abs=0.001)
    for row, e in zip(res.stages, exp["stufen"], strict=True):
        assert row.name == e["name"]
        assert row.planned_remaining_today == pytest.approx(e["soll"], abs=0.01)
        assert row.gap == pytest.approx(e["delta"], abs=0.01)
        assert row.required_kg_per_week == pytest.approx(e["rate_noetig"], abs=0.001)
        assert row.required_pct_per_week == pytest.approx(e["pct"], abs=0.01)
