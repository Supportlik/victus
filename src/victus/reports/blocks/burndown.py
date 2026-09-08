from __future__ import annotations

from datetime import date

from victus.domain.model.reporting import Stage
from victus.domain.services import burndown
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import BurndownDef
from victus.reports.results import BurndownBlockResult


def compute_burndown(block: BurndownDef, ctx: ReportContext) -> BurndownBlockResult:
    s = ctx.settings
    start: date
    if isinstance(block.start, date):
        start = block.start
    elif s.burndown_start is not None:
        start = s.burndown_start
    else:
        start = ctx.period.start

    stages: list[Stage]
    if block.stages == "from_settings":
        stages = list(s.stages)
    else:
        wanted = set(block.stages)
        stages = [st for st in s.stages if st.name in wanted]

    anchor_day = ctx.ma_end
    if anchor_day is None:
        raise ValueError("no weight data — burndown needs a moving average")
    result = burndown.burndown(
        ctx.ma,
        start,
        s.goal_kg,
        s.goal_date,
        anchor_day,
        stages,
        s.kcal_per_kg,
        tdee_ref=ctx.reference_tdee[0],
    )
    if result is None:
        raise ValueError("burndown not computable: no anchor after start or goal already reached")
    return BurndownBlockResult(
        meta=meta_for(block), result=result, goal_kg=s.goal_kg, goal_date=s.goal_date
    )
