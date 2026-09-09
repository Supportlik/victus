"""Metric paths for ``kpi_tile`` blocks (``weight.ma7``, ``goal.deficit_kcal``, …).

Each provider returns a :class:`MetricValue`; unknown paths raise ``KeyError`` so a
typo in a report definition surfaces as a ``BlockError``, not as a blank tile.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from victus.domain.model.reporting import RequiredRate
from victus.domain.services import band_rating, tdee
from victus.domain.values import BandZone, Message, Period, Quality
from victus.reports.context import ReportContext
from victus.reports.messages import basis_message, tdee_from


@dataclass(frozen=True, slots=True)
class MetricValue:
    value: float | None
    unit: str
    decimals: int
    zone: BandZone | None = None
    quality: Quality | None = None
    #: The line under the figure, as a key the interface translates (R78).
    note: Message | None = None


Provider = Callable[[ReportContext], MetricValue]


def _weight_latest(ctx: ReportContext) -> MetricValue:
    lw = ctx.latest_weight
    note = Message("weighed on {date}", {"date": lw[0].isoformat()}) if lw else None
    return MetricValue(lw[1] if lw else None, "kg", 1, note=note)


def _weight_ma(ctx: ReportContext) -> MetricValue:
    days = ctx.settings.moving_average_days
    note = Message("{n}-day moving average", {"n": days})
    return MetricValue(ctx.current_kg, "kg", 1, note=note)


def _weight_delta_week(ctx: ReportContext) -> MetricValue:
    cur = ctx.current_kg
    prev = ctx.ma_at_or_before(ctx.today - timedelta(days=7))
    if cur is None or prev is None:
        return MetricValue(None, "kg", 2)
    note = Message("change of the moving average over {n} days", {"n": 7})
    return MetricValue(round(cur - prev, 2), "kg", 2, note=note)


def _rolling(window: int) -> Provider:
    def provider(ctx: ReportContext) -> MetricValue:
        row = next((r for r in ctx.rolling_for([window])), None)
        if row is None:
            return MetricValue(None, "kcal", 0)
        return MetricValue(
            float(row.tdee) if row.tdee is not None else None,
            "kcal",
            0,
            quality=row.quality,
            note=Message(
                "{n}-day window, {pct} % covered",
                {"n": window, "pct": row.coverage_pct},
            ),
        )

    return provider


def _tdee_reference(ctx: ReportContext) -> MetricValue:
    value, basis = ctx.reference_tdee
    return MetricValue(
        float(value) if value is not None else None, "kcal", 0, note=basis_message(basis)
    )


def _required(ctx: ReportContext) -> RequiredRate | None:
    if ctx.current_kg is None:
        return None
    s = ctx.settings
    return tdee.required_rate(ctx.current_kg, s.goal_kg, s.goal_date, ctx.today, s.kcal_per_kg)


def _goal_rate(ctx: ReportContext) -> MetricValue:
    req = _required(ctx)
    if req is None:
        return MetricValue(None, "kg/week", 2)
    note = Message("{n} days left", {"n": req.days_left})
    return MetricValue(round(req.kg_per_week, 2), "kg/week", 2, note=note)


def _goal_deficit(ctx: ReportContext) -> MetricValue:
    req = _required(ctx)
    if req is None:
        return MetricValue(None, "kcal/day", 0)
    return MetricValue(round(req.deficit_kcal_per_day), "kcal/day", 0)


def _goal_eat(ctx: ReportContext) -> MetricValue:
    req = _required(ctx)
    ref, basis = ctx.reference_tdee
    if req is None or ref is None:
        return MetricValue(None, "kcal/day", 0)
    target = tdee.eat_target(ref, req)
    return MetricValue(
        float(target) if target is not None else None, "kcal/day", 0, note=tdee_from(basis)
    )


def _goal_to_go(ctx: ReportContext) -> MetricValue:
    req = _required(ctx)
    return MetricValue(round(req.to_go_kg, 1) if req else None, "kg", 1)


def _average(macro: str, unit: str, decimals: int) -> Provider:
    def provider(ctx: ReportContext) -> MetricValue:
        series = ctx.macro_series(macro)
        if not series:
            return MetricValue(
                None, unit, decimals, note=Message("no countable days in this period")
            )
        mean = statistics.mean(series.values())
        zone: BandZone | None = None
        if macro == "kcal":
            zone = band_rating.corridor_rating(mean, ctx.settings.corridor)
        else:
            last_day = max(series)
            band = ctx.source.target_band_for(last_day, ctx.period_days[last_day].training_type)
            b = band.band_for(macro) if band else None
            zone = b.zone(mean) if b else None
        return MetricValue(
            round(mean, decimals),
            unit,
            decimals,
            zone=zone,
            note=Message("{n} countable days", {"n": len(series)}),
        )

    return provider


PROVIDERS: dict[str, Provider] = {
    "weight.latest": _weight_latest,
    "weight.ma7": _weight_ma,
    "weight.ma": _weight_ma,
    "weight.delta_week": _weight_delta_week,
    "tdee.rolling_7": _rolling(7),
    "tdee.rolling_14": _rolling(14),
    "tdee.rolling_30": _rolling(30),
    "tdee.reference": _tdee_reference,
    "goal.rate_kg_per_week": _goal_rate,
    "goal.deficit_kcal": _goal_deficit,
    "goal.eat_kcal": _goal_eat,
    "goal.to_go_kg": _goal_to_go,
    "kcal.average": _average("kcal", "kcal", 0),
    "protein.average": _average("protein", "g", 1),
    "carbs.average": _average("carbs", "g", 1),
    "fat.average": _average("fat", "g", 1),
    "fiber.average": _average("fiber", "g", 1),
    "salt.average": _average("salt", "g", 2),
}


def resolve(path: str, ctx: ReportContext) -> MetricValue:
    try:
        provider = PROVIDERS[path]
    except KeyError:
        raise KeyError(f"unknown metric path {path!r}") from None
    return provider(ctx)


def resolve_in(path: str, source: ReportContext, period: Period) -> MetricValue:
    """Resolve ``path`` for another period (used for KPI deltas)."""
    other = ReportContext(source.source, period, period.end)
    return resolve(path, other)
