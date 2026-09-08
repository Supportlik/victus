"""Timeline block: weight, intake, TDEE and macros over one shared time axis.

Everything a person compares by eye when asking "why did the weight move like
that": the moving average, what was eaten, the rolling TDEE ending on each day,
and the macro split. One row per day of the period, so the app can stack the
panels and read them together.
"""

from __future__ import annotations

from datetime import date, timedelta

from victus.domain.services import tdee as tdee_svc
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import TimelineDef
from victus.reports.results import TimelineResult, TimelineRow

MACROS = ("kcal", "protein", "carbs", "fat", "fiber", "salt")


def compute_timeline(block: TimelineDef, ctx: ReportContext) -> TimelineResult:
    s = ctx.settings
    days = [
        ctx.period.start + timedelta(days=i)
        for i in range((ctx.period.end - ctx.period.start).days + 1)
    ]
    if not days:
        raise ValueError("empty period")

    series: dict[str, dict[date, float]] = {m: ctx.macro_series(m) for m in MACROS}
    rows: list[TimelineRow] = []
    for day in days:
        dm = ctx.period_days.get(day)
        rows.append(
            TimelineRow(
                date=day,
                weight=ctx.weights.get(day),
                weight_ma=ctx.ma.get(day),
                countable=bool(dm.countable) if dm else False,
                tdee=_rolling_tdee(ctx, day, block.tdee_window),
                **{m: series[m].get(day) for m in MACROS},
            )
        )

    # the corridor is the honest reference for "how much should be on the plate"
    return TimelineResult(
        meta=meta_for(block),
        rows=rows,
        tdee_window=block.tdee_window,
        goal_kg=s.goal_kg,
        kcal_min=float(s.corridor.min),
        kcal_max=float(s.corridor.max),
    )


def _rolling_tdee(ctx: ReportContext, day: date, window: int) -> int | None:
    """The rolling TDEE of the window ending on ``day`` (None when too thin)."""
    if day not in ctx.ma:
        return None
    row = tdee_svc.rolling_window(
        ctx.weights,
        ctx.ma,
        ctx.calories,
        ctx.protein,
        window,
        ctx.settings.kcal_per_kg,
        ctx.settings.corridor,
        end=day,
    )
    return row.tdee if row else None
