from __future__ import annotations

from victus.domain.services import trend
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import TrendDef
from victus.reports.results import TrendResult


def compute_trend(block: TrendDef, ctx: ReportContext) -> TrendResult:
    if ctx.ma_end is None:
        raise ValueError("no weight data — trend needs a moving average")
    windows = block.windows or list(ctx.settings.trend_windows)
    rows = trend.trend_windows(ctx.ma, ctx.weights, windows, today=ctx.ma_end)
    return TrendResult(meta=meta_for(block), rows=rows)
