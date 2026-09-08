from __future__ import annotations

from victus.reports import metrics
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import KpiTileDef
from victus.reports.results import KpiTileResult


def compute_kpi_tile(block: KpiTileDef, ctx: ReportContext) -> KpiTileResult:
    mv = metrics.resolve(block.source, ctx)
    delta: float | None = None
    if block.delta_to:
        other = metrics.resolve(block.delta_to, ctx)
        if mv.value is not None and other.value is not None:
            delta = round(mv.value - other.value, block.decimals or mv.decimals)
    elif mv.value is not None:
        previous = metrics.resolve_in(block.source, ctx, ctx.previous_period())
        if previous.value is not None:
            delta = round(mv.value - previous.value, block.decimals or mv.decimals)
    return KpiTileResult(
        meta=meta_for(block),
        source=block.source,
        value=mv.value,
        unit=block.unit or mv.unit,
        decimals=block.decimals if block.decimals is not None else mv.decimals,
        delta=delta,
        zone=mv.zone,
        quality=mv.quality,
        note=mv.note,
    )
