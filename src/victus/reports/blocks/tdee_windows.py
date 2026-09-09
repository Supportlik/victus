from __future__ import annotations

from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import TdeeWindowsDef
from victus.reports.messages import basis_message
from victus.reports.results import TdeeWindowsResult


def compute_tdee_windows(block: TdeeWindowsDef, ctx: ReportContext) -> TdeeWindowsResult:
    if not ctx.ma:
        raise ValueError("no weight data — TDEE windows need a moving average")
    rows = ctx.rolling_for(block.windows)
    ref, basis = ctx.reference_tdee
    return TdeeWindowsResult(
        meta=meta_for(block),
        rows=rows,
        show_quality=block.show_quality,
        reference_tdee=ref,
        reference_basis=basis_message(basis),
    )
