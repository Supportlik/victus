from __future__ import annotations

from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import WeeklyChartDef
from victus.reports.results import WeeklyChartResult


def compute_weekly_chart(block: WeeklyChartDef, ctx: ReportContext) -> WeeklyChartResult:
    rows = ctx.weekly[-block.weeks :] if block.weeks else ctx.weekly
    if not rows:
        raise ValueError("no weekly data")
    return WeeklyChartResult(meta=meta_for(block), rows=rows, series=list(block.series))
