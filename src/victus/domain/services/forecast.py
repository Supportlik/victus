"""Weight forecast per trend window — a fan, not a single line.

Deliberately no 12-month extrapolation: horizons stay at 1/3/6 months and the
goal date is always shown alongside (predecessor ``prognose_table``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from victus.domain.model.reporting import ForecastRow, TrendRow

DAYS_1M = 30.44
DAYS_3M = 91.31
DAYS_6M = 182.62
ETA_MIN_SLOPE = -0.001


def eta(remaining_kg: float, slope_per_day: float | None, today: date) -> date | None:
    """The day ``remaining_kg`` above the goal is gone at ``slope_per_day``.

    ``None`` when the slope is unknown, flat or rising (``slope >= ETA_MIN_SLOPE``)
    or nothing remains. The forecast ETA and the burndown projection both come
    from here, so the two blocks cannot name different days for one window.
    """
    if slope_per_day is None or not slope_per_day < ETA_MIN_SLOPE or remaining_kg <= 0:
        return None
    return today + timedelta(days=int(remaining_kg / -slope_per_day))


def forecast(
    trends: Sequence[TrendRow],
    current_kg: float,
    today: date,
    goal_kg: float,
    goal_date: date,
) -> list[ForecastRow]:
    out: list[ForecastRow] = []
    for t in trends:
        slope = t.slope_per_day
        if slope is None:
            out.append(ForecastRow(t.window, t.kg_per_week, None, None, None, None, None))
            continue
        out.append(
            ForecastRow(
                window=t.window,
                kg_per_week=t.kg_per_week,
                m1=current_kg + slope * DAYS_1M,
                m3=current_kg + slope * DAYS_3M,
                m6=current_kg + slope * DAYS_6M,
                at_goal_date=current_kg + slope * max((goal_date - today).days, 0),
                eta=eta(current_kg - goal_kg, slope, today),
            )
        )
    return out
