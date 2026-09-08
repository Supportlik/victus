"""Reports: list definitions and render one for a period (JSON or Markdown)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from victus.api.deps import Ctx, Uow
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
