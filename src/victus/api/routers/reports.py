"""Reports: list definitions and render one for a period (JSON or Markdown)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from victus.api.deps import Ctx, Uow
from victus.application.use_cases import snapshots as snap_uc
from victus.domain.values import Period
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.reports.sqlalchemy_source import SqlAlchemyReportDataSource
from victus.reports.definition import ReportDefinition
from victus.reports.engine import ReportEngine
from victus.reports.registry import ReportRegistry
from victus.reports.render.json import to_dict
from victus.reports.render.markdown import to_markdown

router = APIRouter(tags=["reports"])
_registry = ReportRegistry()


class SnapshotOut(BaseModel):
    id: str
    report_name: str
    title: str
    label: str | None = None
    period_start: date
    period_end: date
    today: date
    status: str
    created_at: datetime
    created_by: str | None = None
    assessment_md: str | None = None
    assessed_at: datetime | None = None
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    result: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class AssessIn(BaseModel):
    markdown: str
    model: str | None = None


class PeriodSpecOut(BaseModel):
    default: str
    options: list[str]


class ReportInfo(BaseModel):
    name: str
    title: str
    description: str | None = None
    builtin: bool
    period: PeriodSpecOut


def _info(definition: ReportDefinition) -> ReportInfo:
    return ReportInfo(
        name=definition.name,
        title=definition.title,
        description=definition.description,
        builtin=_registry.is_builtin(definition.name),
        period=PeriodSpecOut(
            default=definition.period.default, options=list(definition.period.options)
        ),
    )


def _definition(name: str) -> ReportDefinition:
    try:
        return _registry.get(name)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown report {name!r}") from exc


def _period(
    definition: ReportDefinition, from_: date | None, to: date | None, today: date
) -> Period:
    if from_ and to:
        if to < from_:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'to' lies before 'from'")
        return Period(from_, to)
    if from_ or to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "pass both 'from' and 'to'")
    try:
        return definition.default_period(today)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _render(
    ctx: Any, uow_factory: Any, name: str, fmt: str, from_: date | None, to: date | None
) -> Response | dict[str, Any]:
    definition = _definition(name)
    today = datetime.now(UTC).date()
    period = _period(definition, from_, to, today)
    with uow_factory(ctx) as uow:
        source = SqlAlchemyReportDataSource(cast(SqlAlchemyUnitOfWork, uow))
        result = ReportEngine(source).render(definition, period, today=today)
    if fmt == "markdown":
        return Response(content=to_markdown(result), media_type="text/markdown; charset=utf-8")
    payload = to_dict(result)
    # The web client reads a flat `from`/`to` next to the nested `period`.
    payload["from"] = period.start.isoformat()
    payload["to"] = period.end.isoformat()
    payload["today"] = today.isoformat()
    return payload


def _freeze(
    ctx: Any, uow_factory: Any, name: str, from_: date | None, to: date | None, label: str | None
) -> Any:
    """Render the report and store it as a snapshot (the numbers never change again)."""
    definition = _definition(name)
    today = datetime.now(UTC).date()
    period = _period(definition, from_, to, today)
    with uow_factory(ctx) as uow:
        source = SqlAlchemyReportDataSource(cast(SqlAlchemyUnitOfWork, uow))
        result = ReportEngine(source).render(definition, period, today=today)
    payload = to_dict(result)
    payload["from"] = period.start.isoformat()
    payload["to"] = period.end.isoformat()
    payload["today"] = today.isoformat()
    return snap_uc.FreezeReport(uow_factory, ctx).execute(
        definition.name,
        definition.title,
        payload,
        period_start=period.start,
        period_end=period.end,
        today=today,
        label=label,
    )


@router.post(
    "/reports/{name}/snapshots",
    response_model=SnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze a report as a snapshot the agent can assess",
)
def create_snapshot(
    name: str,
    ctx: Ctx,
    uow: Uow,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    label: Annotated[str | None, Query(max_length=200)] = None,
) -> SnapshotOut:
    return SnapshotOut.model_validate(_freeze(ctx, uow, name, from_, to, label))


@router.get("/reports/snapshots", response_model=list[SnapshotOut])
def list_snapshots(
    ctx: Ctx,
    uow: Uow,
    report: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SnapshotOut]:
    rows = snap_uc.ListSnapshots(uow, ctx).execute(report_name=report, limit=limit)
    return [SnapshotOut.model_validate(r) for r in rows]


@router.get("/reports/snapshots/{snapshot_id}", response_model=SnapshotOut)
def get_snapshot(snapshot_id: str, ctx: Ctx, uow: Uow) -> SnapshotOut:
    return SnapshotOut.model_validate(snap_uc.GetSnapshot(uow, ctx).execute(snapshot_id))


@router.post("/reports/snapshots/{snapshot_id}/assess", response_model=SnapshotOut)
def assess_snapshot(snapshot_id: str, body: AssessIn, ctx: Ctx, uow: Uow) -> SnapshotOut:
    view = snap_uc.AssessSnapshot(uow, ctx).execute(
        snapshot_id, body.markdown, model=body.model, prompt_version="manual"
    )
    return SnapshotOut.model_validate(view)


@router.delete("/reports/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(snapshot_id: str, ctx: Ctx, uow: Uow) -> Response:
    snap_uc.DeleteSnapshot(uow, ctx).execute(snapshot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/reports", response_model=list[ReportInfo], summary="Available report definitions")
def list_reports(ctx: Ctx) -> list[ReportInfo]:
    ctx.require("read")
    return [_info(d) for d in _registry.list()]


@router.post(
    "/reports/{name}/render",
    summary="Render a report for a period",
    response_model=None,
)
def render_report(
    name: str,
    ctx: Ctx,
    uow: Uow,
    format: Annotated[Literal["json", "markdown"], Query()] = "json",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> Response | dict[str, Any]:
    ctx.require("read")
    return _render(ctx, uow, name, format, from_, to)


@router.get(
    "/reports/checkup",
    summary="Shortcut: the built-in check-up for the default period",
    response_model=None,
)
def checkup(
    ctx: Ctx,
    uow: Uow,
    format: Annotated[Literal["json", "markdown"], Query()] = "json",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> Response | dict[str, Any]:
    ctx.require("read")
    return _render(ctx, uow, "checkup", format, from_, to)
