"""Burndown: remaining kilograms above the goal, planned versus actual.

Classic burndown semantics (predecessor, 26 Aug 2026): the *remaining amount*
(kg above goal) is plotted, not the weight. The actual line **below** the planned
line means ahead of plan. One planned line per named stage; all start at the
anchor and reach zero on the stage date.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from victus.domain.model.reporting import BurndownResult, Stage, StageRow

MUSCLE_LOSS_PCT_PER_WEEK = 1.1  # % of body weight per week, with tolerance
MIN_EAT_KCAL = 1200.0


def planned_path(
    anchor: date, remaining_at_anchor: float, stage_date: date, step: int = 3
) -> list[tuple[date, float]]:
    """Linear planned line from the anchor to zero on ``stage_date``.

    The end point is appended explicitly: ``range(…, step)`` does not land on
    the last day unless ``days % step == 0`` and the line would end above zero.
    """
    days = (stage_date - anchor).days
    if days <= 0:
        return [(anchor, remaining_at_anchor), (stage_date, 0.0)]
    pts = [
        (anchor + timedelta(days=i), remaining_at_anchor * (1 - i / days))
        for i in range(0, days, step)
    ]
    pts.append((stage_date, 0.0))
    return pts


def burndown(
    ma: Mapping[date, float],
    start: date,
    goal_kg: float,
    goal_date: date,
    today: date,
    stages: Sequence[Stage],
    kcal_per_kg: float,
    tdee_ref: int | None = None,
    end: date | None = None,
) -> BurndownResult | None:
    """Compute the burndown from the first MA point at or after ``start``.

    Returns ``None`` when there is no anchor or the current weight is already at
    or below the goal. ``end`` limits which stages are shown (default: no limit).
    """
    anchor = min((d for d in ma if d >= start), default=None)
    if anchor is None or today not in ma:
        return None
    current = ma[today]
    if current <= goal_kg:
        return None

    remaining0 = ma[anchor] - goal_kg
    remaining_today = current - goal_kg
    elapsed = (today - anchor).days
    total_days = max((goal_date - anchor).days, 1)
    planned_today = remaining0 * (1 - elapsed / total_days)

    rows: list[StageRow] = []
    for st in sorted(stages, key=lambda s: s.date):
        if not (anchor < st.date and (end is None or st.date <= end)):
            continue
        days = (st.date - anchor).days
        planned = remaining0 * (1 - elapsed / days)
        weeks_left = max((st.date - today).days / 7, 0.01)
        rate = remaining_today / weeks_left
        pct = rate / current * 100 if current else 0.0
        eat = (tdee_ref - rate * kcal_per_kg / 7) if tdee_ref is not None else None
        feasible = not (pct > MUSCLE_LOSS_PCT_PER_WEEK or (eat is not None and eat < MIN_EAT_KCAL))
        rows.append(
            StageRow(
                name=st.name,
                date=st.date,
                planned_remaining_today=planned,
                gap=planned - remaining_today,
                required_kg_per_week=rate,
                required_pct_per_week=pct,
                eat_kcal_per_day=eat,
                feasible=feasible,
            )
        )

    return BurndownResult(
        anchor=anchor,
        remaining_at_anchor=remaining0,
        remaining_today=remaining_today,
        planned_remaining_today=planned_today,
        gap=planned_today - remaining_today,
        burned=remaining0 - remaining_today,
        days_elapsed=elapsed,
        actual_rate_per_week=(remaining0 - remaining_today) / (elapsed / 7) if elapsed else 0.0,
        planned_rate_per_week=remaining0 / max(total_days / 7, 1),
        required_rate_per_week=remaining_today / max((goal_date - today).days / 7, 1),
        target_path=planned_path(anchor, remaining0, goal_date),
        actual=[(d, v - goal_kg) for d, v in sorted(ma.items()) if anchor <= d <= today],
        stages=rows,
    )
