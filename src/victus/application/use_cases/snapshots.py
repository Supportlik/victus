"""Report snapshots: freeze a rendered report, then let the model assess it (SPEC R57).

A snapshot is a moment: the numbers of a period, frozen with the date they were
computed, plus one written assessment of where things stand. Later data never
changes a snapshot, so an assessment always refers to what it actually saw.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
)
from victus.application.use_cases._base import UseCase, now
from victus.infrastructure.db import orm

FROZEN, ASSESSED, FAILED = "frozen", "assessed", "failed"


def snapshot_view(row: orm.ReportSnapshot, *, with_result: bool) -> dto.ReportSnapshotView:
    return dto.ReportSnapshotView(
        id=row.id,
        report_name=row.report_name,
        title=row.title,
        label=row.label,
        period_start=row.period_start,
        period_end=row.period_end,
        today=row.today,
        status=row.status,
        created_at=row.created_at,
        created_by=row.created_by,
        assessment_md=row.assessment_md,
        assessed_at=row.assessed_at,
        model=row.model,
        prompt_version=row.prompt_version,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_usd=row.cost_usd,
        result=dict(row.result) if with_result else None,
    )


class FreezeReport(UseCase):
    """Store an already rendered report as a snapshot.

    The rendering happens in the adapter that owns the report engine (API, MCP,
    worker); this use case only records the result.
    """

    def execute(
        self,
        report_name: str,
        title: str,
        result: dict[str, Any],
        *,
        period_start: date,
        period_end: date,
        today: date,
        label: str | None = None,
    ) -> dto.ReportSnapshotView:
        self.ctx.require(SCOPE_READ)
        if not result:
            raise ValidationFailed("a snapshot needs a rendered report")
        with self._uow() as uow:
            row = uow.snapshots.add(
                orm.ReportSnapshot(
                    tenant_id=self.ctx.tenant_id,
                    report_name=report_name,
                    title=title,
                    label=(label or None),
                    period_start=period_start,
                    period_end=period_end,
                    today=today,
                    status=FROZEN,
                    result=result,
                    created_by=self.ctx.actor_kind,
                )
            )
            uow.audit.record(
                "report.freeze",
                "report_snapshot",
                row.id,
                {
                    "report": report_name,
                    "period": [period_start.isoformat(), period_end.isoformat()],
                },
            )
            uow.flush()
            view = snapshot_view(row, with_result=False)
            uow.commit()
            return view


class ListSnapshots(UseCase):
    def execute(
        self, *, report_name: str | None = None, limit: int = 50
    ) -> list[dto.ReportSnapshotView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.snapshots.list(report_name=report_name, limit=limit)
            return [snapshot_view(r, with_result=False) for r in rows]


class GetSnapshot(UseCase):
    def execute(self, snapshot_id: str, *, with_result: bool = True) -> dto.ReportSnapshotView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            row = uow.snapshots.get(snapshot_id)
            if row is None:
                raise NotFound(f"snapshot {snapshot_id} not found")
            return snapshot_view(row, with_result=with_result)


class PendingSnapshots(UseCase):
    """Snapshots waiting for an assessment; the worker's queue."""

    def execute(self, *, limit: int = 10) -> list[dto.ReportSnapshotView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.snapshots.list(status=FROZEN, limit=limit)
            return [snapshot_view(r, with_result=True) for r in rows]


class AssessSnapshot(UseCase):
    """Attach the written assessment. The numbers stay as they were frozen."""

    def execute(
        self,
        snapshot_id: str,
        markdown: str,
        *,
        model: str | None = None,
        prompt_version: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        run_id: str | None = None,
    ) -> dto.ReportSnapshotView:
        if not (self.ctx.has_scope(SCOPE_AGENT_WRITE) or self.ctx.has_scope(SCOPE_WRITE)):
            self.ctx.require(SCOPE_AGENT_WRITE)
        text = markdown.strip()
        if not text:
            raise ValidationFailed("an assessment needs text")
        with self._uow() as uow:
            row = uow.snapshots.get(snapshot_id)
            if row is None:
                raise NotFound(f"snapshot {snapshot_id} not found")
            if row.status == ASSESSED:
                raise Conflict(f"snapshot {snapshot_id} already carries an assessment")
            row.assessment_md = text
            row.assessed_at = now()
            row.status = ASSESSED
            row.model = model
            row.prompt_version = prompt_version
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            row.cost_usd = cost_usd
            row.run_id = run_id
            uow.audit.record(
                "report.assess", "report_snapshot", row.id, {"model": model, "cost_usd": cost_usd}
            )
            uow.flush()
            view = snapshot_view(row, with_result=False)
            uow.commit()
            return view


class MarkSnapshotFailed(UseCase):
    def execute(self, snapshot_id: str, error: str) -> dto.ReportSnapshotView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            row = uow.snapshots.get(snapshot_id)
            if row is None:
                raise NotFound(f"snapshot {snapshot_id} not found")
            row.status = FAILED
            row.assessment_md = error[:2000]
            row.assessed_at = now()
            uow.flush()
            view = snapshot_view(row, with_result=False)
            uow.commit()
            return view


class DeleteSnapshot(UseCase):
    def execute(self, snapshot_id: str) -> None:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            row = uow.snapshots.get(snapshot_id)
            if row is None:
                raise NotFound(f"snapshot {snapshot_id} not found")
            uow.audit.record("report.snapshot.delete", "report_snapshot", row.id, None)
            uow.snapshots.delete(row)
            uow.commit()
