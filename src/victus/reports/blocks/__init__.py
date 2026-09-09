"""One small class per block type; ``compute(definition, ctx)`` returns a result or raises."""

from __future__ import annotations

from collections.abc import Callable

from victus.reports import definition as d
from victus.reports.blocks.band_distribution import compute_band_distribution
from victus.reports.blocks.body import compute_body_composition, compute_energy_split
from victus.reports.blocks.burndown import compute_burndown
from victus.reports.blocks.day_list import compute_day_list
from victus.reports.blocks.forecast import compute_forecast
from victus.reports.blocks.kpi_tile import compute_kpi_tile
from victus.reports.blocks.tdee_windows import compute_tdee_windows
from victus.reports.blocks.text_finding import compute_text_finding
from victus.reports.blocks.timeline import compute_timeline
from victus.reports.blocks.trend import compute_trend
from victus.reports.blocks.weekly_chart import compute_weekly_chart
from victus.reports.context import ReportContext
from victus.reports.results import BlockResult

Compute = Callable[[d.BlockDef, ReportContext], BlockResult]

COMPUTERS: dict[str, Compute] = {
    "kpi_tile": lambda b, c: compute_kpi_tile(_as(b, d.KpiTileDef), c),
    "band_distribution": lambda b, c: compute_band_distribution(_as(b, d.BandDistributionDef), c),
    "tdee_windows": lambda b, c: compute_tdee_windows(_as(b, d.TdeeWindowsDef), c),
    "trend": lambda b, c: compute_trend(_as(b, d.TrendDef), c),
    "forecast": lambda b, c: compute_forecast(_as(b, d.ForecastDef), c),
    "burndown": lambda b, c: compute_burndown(_as(b, d.BurndownDef), c),
    "weekly_chart": lambda b, c: compute_weekly_chart(_as(b, d.WeeklyChartDef), c),
    "timeline": lambda b, c: compute_timeline(_as(b, d.TimelineDef), c),
    "day_list": lambda b, c: compute_day_list(_as(b, d.DayListDef), c),
    "text_finding": lambda b, c: compute_text_finding(_as(b, d.TextFindingDef), c),
    "body_composition": lambda b, c: compute_body_composition(_as(b, d.BodyCompositionDef), c),
    "energy_split": lambda b, c: compute_energy_split(_as(b, d.EnergySplitDef), c),
}


def _as[T](block: object, kind: type[T]) -> T:
    if not isinstance(block, kind):
        raise TypeError(f"expected {kind.__name__}, got {type(block).__name__}")
    return block
