from __future__ import annotations

from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import DayListDef
from victus.reports.results import DayListResult, DayListRow


def compute_day_list(block: DayListDef, ctx: ReportContext) -> DayListResult:
    rows: list[DayListRow] = []
    for day in sorted(ctx.period_days, reverse=True)[: block.limit]:
        dm = ctx.period_days[day]
        rows.append(
            DayListRow(
                date=day,
                macros=dm.macros,
                weight=ctx.weights.get(day),
                training_type=dm.training_type,
                status=dm.status,
                reliable=dm.reliable,
                countable=dm.countable,
            )
        )
    return DayListResult(meta=meta_for(block), columns=list(block.columns), rows=rows)
