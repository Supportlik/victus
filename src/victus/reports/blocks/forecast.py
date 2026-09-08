from __future__ import annotations

from victus.domain.services import forecast, trend
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import ForecastDef
from victus.reports.results import ForecastResult


def compute_forecast(block: ForecastDef, ctx: ReportContext) -> ForecastResult:
    if ctx.ma_end is None or ctx.current_kg is None:
        raise ValueError("no weight data — forecast needs a moving average")
    s = ctx.settings
    trends = trend.trend_windows(ctx.ma, ctx.weights, list(s.trend_windows), today=ctx.ma_end)
    rows = forecast.forecast(trends, ctx.current_kg, ctx.today, s.goal_kg, s.goal_date)
    return ForecastResult(
        meta=meta_for(block),
        rows=rows,
        horizons=list(block.horizons),
        with_eta=block.with_eta,
        current_kg=ctx.current_kg,
        goal_kg=s.goal_kg,
        goal_date=s.goal_date,
    )
