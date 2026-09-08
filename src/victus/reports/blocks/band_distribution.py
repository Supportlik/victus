from __future__ import annotations

import statistics

from victus.domain.model.reporting import BandStat
from victus.domain.values import Band, BandZone
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import BandDistributionDef
from victus.reports.results import BandDistributionResult, BandDistributionRow


def _corridor_row(macro: str, ctx: ReportContext) -> BandDistributionRow:
    """kcal is rated against the (possibly asymmetric) corridor, not a band."""
    series = ctx.macro_series(macro)
    corridor = ctx.settings.corridor
    counts = dict.fromkeys(BandZone, 0)
    for v in series.values():
        if v > corridor.max:
            counts[BandZone.ABOVE_MAX] += 1
        elif v < corridor.min and not corridor.asymmetric:
            counts[BandZone.BELOW_MIN] += 1
        elif v < corridor.min:
            counts[BandZone.BELOW_OPTIMUM] += 1
        else:
            counts[BandZone.OPTIMAL] += 1
    stat = BandStat(
        below_min=counts[BandZone.BELOW_MIN],
        below_optimum=counts[BandZone.BELOW_OPTIMUM],
        optimal=counts[BandZone.OPTIMAL],
        above_optimum=counts[BandZone.ABOVE_OPTIMUM],
        above_max=counts[BandZone.ABOVE_MAX],
        mean=round(statistics.mean(series.values()), 2) if series else None,
        n=len(series),
    )
    band = Band(
        min=corridor.min,
        opt_min=corridor.min,
        opt_max=corridor.max,
        target=corridor.max,
        max=corridor.max,
    )
    return BandDistributionRow(macro=macro, stat=stat, band=band, days_rated=len(series))


def _band_row(macro: str, ctx: ReportContext) -> BandDistributionRow:
    """Every day is rated against *its own* band (bands vary by training type and date)."""
    series = ctx.macro_series(macro)
    counts = dict.fromkeys(BandZone, 0)
    rated = 0
    last_band: Band | None = None
    for day in sorted(series):
        dm = ctx.period_days[day]
        profile = ctx.source.target_band_for(day, dm.training_type)
        band = profile.band_for(macro) if profile else None
        if band is None:
            continue
        counts[band.zone(series[day])] += 1
        rated += 1
        last_band = band
    stat = BandStat(
        below_min=counts[BandZone.BELOW_MIN],
        below_optimum=counts[BandZone.BELOW_OPTIMUM],
        optimal=counts[BandZone.OPTIMAL],
        above_optimum=counts[BandZone.ABOVE_OPTIMUM],
        above_max=counts[BandZone.ABOVE_MAX],
        mean=round(statistics.mean(series.values()), 2) if series else None,
        n=len(series),
    )
    return BandDistributionRow(macro=macro, stat=stat, band=last_band, days_rated=rated)


def compute_band_distribution(
    block: BandDistributionDef, ctx: ReportContext
) -> BandDistributionResult:
    rows = [_corridor_row(m, ctx) if m == "kcal" else _band_row(m, ctx) for m in block.macros]
    return BandDistributionResult(meta=meta_for(block), rows=rows)
