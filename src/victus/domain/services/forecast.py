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
        eta: date | None = None
        if slope < ETA_MIN_SLOPE and current_kg > goal_kg:
            eta = today + timedelta(days=int((current_kg - goal_kg) / -slope))
        out.append(
            ForecastRow(
                window=t.window,
                kg_per_week=t.kg_per_week,
                m1=current_kg + slope * DAYS_1M,
                m3=current_kg + slope * DAYS_3M,
                m6=current_kg + slope * DAYS_6M,
                at_goal_date=current_kg + slope * max((goal_date - today).days, 0),
                eta=eta,
            )
        )
    return out
