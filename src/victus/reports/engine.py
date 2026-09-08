"""Render a report definition into a :class:`ReportResult`.

A block that cannot be computed becomes a :class:`BlockError`; the other blocks
still render. Nothing here writes anywhere.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from victus.application.ports.report_data import ReportDataSource
from victus.domain.values import Period
from victus.reports.blocks import COMPUTERS
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import ReportDefinition, parse_period_token
from victus.reports.results import BlockError, BlockResult, ReportResult


class ReportEngine:
    def __init__(self, source: ReportDataSource) -> None:
        self.source = source

    def render(
        self,
        definition: ReportDefinition,
        period: Period | None = None,
        today: date | None = None,
        *,
        now: datetime | None = None,
    ) -> ReportResult:
        today = today or datetime.now(UTC).date()
        period = period or parse_period_token(definition.period.default, today)
        ctx = ReportContext(self.source, period, today)
        blocks: list[BlockResult] = []
        for block in definition.blocks:
            compute = COMPUTERS.get(block.type)
            if compute is None:  # pragma: no cover - definition validation prevents this
                blocks.append(BlockError(meta_for(block), f"unknown block type {block.type!r}"))
                continue
            try:
                blocks.append(compute(block, ctx))
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                blocks.append(BlockError(meta_for(block), str(exc).strip("'\"")))
        return ReportResult(
            name=definition.name,
            title=definition.title,
            description=definition.description,
            period=period,
            today=today,
            generated_at=now or datetime.now(UTC),
            blocks=blocks,
        )
