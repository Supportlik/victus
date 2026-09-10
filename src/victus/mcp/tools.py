"""The one tool registry behind the MCP server and the in-house worker (SPEC R41).

Every tool is a thin adapter over a use case: a pydantic input model (the JSON
schema clients see), the scope it needs, and a handler bound to a
:class:`ToolContext`. The MCP server registers these for stdio/HTTP clients;
the worker converts the same specs into Anthropic ``tools`` definitions and
dispatches the model's calls through :func:`dispatch`. Authorisation is
enforced twice — here for a clear early error, and in the use cases.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import enum
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from victus.application import dto
from victus.application.errors import ApplicationError
from victus.application.ports.blob_storage import BlobStorage
from victus.application.ports.transcription import TranscriptionPort
from victus.application.schemas_loader import load_schema
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeError,
    TenantContext,
)
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import body as body_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import drafts as draft_uc
from victus.application.use_cases import products as product_uc
from victus.application.use_cases import proposals as proposal_uc
from victus.application.use_cases import recipes as recipe_uc
from victus.application.use_cases import rules as rules_uc
from victus.application.use_cases import snapshots as snapshot_uc
from victus.application.use_cases import weights as weight_uc
from victus.application.use_cases._base import UowFactory
from victus.application.use_cases.settings import Regional, regional_of
from victus.config.server import ServerConfig
from victus.domain.services.calendar import today_in
from victus.domain.values import CaptureKind, CaptureStatus, Period
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.reports.sqlalchemy_source import SqlAlchemyReportDataSource
from victus.reports.definition import parse_period_token
from victus.reports.engine import ReportEngine
from victus.reports.registry import ReportRegistry
from victus.reports.render.json import to_dict
from victus.reports.render.markdown import to_markdown

# ── context, results, errors ────────────────────────────────────────────────


@dataclass(slots=True)
class ToolContext:
    """Everything a tool handler needs; built once per MCP session or worker run."""

    uow_factory: UowFactory
    ctx: TenantContext
    config: ServerConfig
    blobs: BlobStorage | None = None
    transcription: TranscriptionPort | None = None
    run_id: str | None = None
    #: Set by the in-house runner so a written assessment records which prompt produced it.
    prompt_version: str | None = None


@dataclass(frozen=True, slots=True)
class ImageResult:
    """An image payload (base64) plus a text caption; MCP and Anthropic both accept it."""

    data_b64: str
    mime: str
    text: str


class ToolError(Exception):
    """A typed, user-readable tool failure (never a stack trace)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


ToolResult = dict[str, Any] | list[Any] | str | ImageResult
Handler = Callable[[ToolContext, Any], ToolResult]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    scope: str
    input_model: type[BaseModel]
    handler: Handler
    read_only: bool = True
    # When set, this JSON schema is published instead of the pydantic model's.
    input_schema_override: dict[str, Any] | None = None

    def input_schema(self) -> dict[str, Any]:
        if self.input_schema_override is not None:
            return self.input_schema_override
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("additionalProperties", False)
        return schema


def jsonable(value: Any) -> Any:
    """Turn DTO dataclasses, dates, enums and pydantic models into plain JSON values."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):  # PostgreSQL NUMERIC columns
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k) if not isinstance(k, str) else k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    return str(value)


# ── input models ────────────────────────────────────────────────────────────


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductSearchIn(_In):
    q: str = Field(description="Free text as the user said it, e.g. 'skyr' or 'rye bread'.")
    limit: int = Field(default=10, ge=1, le=50)
    on: date | None = Field(
        default=None,
        description=(
            "Day the food was eaten. A product whose values changed over time returns the "
            "version that applied then, so an older day keeps its own numbers. Pass the day "
            "you are drafting."
        ),
    )


class ProductGetIn(_In):
    id: int = Field(description="Product (consumable) id.")


class BodyMeasurementsIn(_In):
    limit: int = Field(default=5, ge=1, le=100, description="Newest sessions to return.")


class BodyAddIn(_In):
    """One tape-measure session, in centimetres. Give only what was actually measured."""

    measured_at: datetime = Field(
        description="When it was measured. Use the capture's time when it came from one."
    )
    waist_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    belly_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    hip_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    chest_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    neck_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    thigh_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    arm_cm: float | None = Field(default=None, gt=0, le=250, description="Centimetres.")
    body_fat_pct: float | None = Field(default=None, ge=3, le=70)
    note: str | None = Field(default=None, description="One sentence, e.g. where it came from.")


class ProductVersionsIn(_In):
    id: int = Field(description="Any version of the product; the whole history is returned.")


class ProductVersionCreateIn(_In):
    id: int = Field(description="The version to replace, usually the current one.")
    valid_from: date = Field(description="First day the new values apply.")
    changes: dict[str, Any] = Field(
        description=(
            "Only the fields that changed, e.g. {'kcal': 112, 'protein': 8.4}. Everything "
            "else is copied from the version being replaced, portions included."
        )
    )


class RecipeGetIn(_In):
    id: int = Field(description="Recipe id.")


class DayGetIn(_In):
    date: dt.date


class DaysListIn(_In):
    from_: dt.date = Field(alias="from")
    to: dt.date
    status: Literal["draft", "open", "closed"] | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NoArgsIn(_In):
    pass


class DayThreadGetIn(_In):
    date: dt.date
    include_processed: bool = Field(
        default=False, description="Also return captures already processed or discarded."
    )


class DayMessageAddIn(_In):
    date: dt.date
    text: str = Field(min_length=1)


class AgentMessageAddIn(_In):
    run_id: str
    date: dt.date
    kind: Literal["summary", "note", "question", "correction"] = Field(
        description="'summary' is the day's verdict: writing one replaces the day's previous."
    )
    content: str = Field(min_length=1)


class DraftSummaryIn(_In):
    date: dt.date


class ReportRenderIn(_In):
    name: str = Field(default="checkup", description="Report name, e.g. 'checkup'.")
    period: str | None = Field(
        default=None, description="Fixed-length period token such as '14d' or '30d'."
    )
    from_: dt.date | None = Field(default=None, alias="from")
    to: dt.date | None = None
    as_of: dt.date | None = Field(
        default=None, description="Compute it as of this day instead of today."
    )
    format: Literal["markdown", "json"] = "markdown"

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CapturesOpenIn(_In):
    date: dt.date | None = Field(
        default=None, description="Only captures for this day (defaults to the run's locked days)."
    )
    scope: Literal["day", "product", "all"] = Field(
        default="day",
        description=(
            "day: captures about days (default). product: captures attached to one product "
            "(label photos, corrections) that carry product_id. all: both."
        ),
    )


class CaptureGetIn(_In):
    id: str
    attachment_id: str | None = Field(
        default=None,
        description="Which file to return when the capture carries several (default: the first).",
    )


class CaptureMarkIn(_In):
    id: str
    status: Literal["new", "in_progress", "assigned", "processed", "discarded", "failed"] | None = (
        None
    )
    target_date: dt.date | None = None
    product_id: int | None = None


class LineItemApproveIn(_In):
    line_item_id: int
    amount: float | None = None
    unit_code: str | None = None
    consumable_id: int | None = None
    meal_id: int | None = Field(default=None, description="Move it to this meal of the same day.")
    meal_name: str | None = Field(
        default=None, description="Move it to the meal with this name, creating it if needed."
    )


class ReportSnapshotCreateIn(_In):
    name: str = Field(default="checkup", description="Report definition to freeze.")
    as_of: dt.date | None = Field(
        default=None, description="Compute it as of this day instead of today."
    )
    period: str | None = Field(default=None, description="e.g. '14d'; omit for the report default.")
    start: dt.date | None = Field(default=None, description="Explicit period start.")
    end: dt.date | None = Field(default=None, description="Explicit period end.")
    label: str | None = None


class ReportSnapshotsListIn(_In):
    report: str | None = None
    limit: int = Field(default=20, ge=1, le=200)


class ReportSnapshotGetIn(_In):
    snapshot_id: str


class ReportAssessIn(_In):
    snapshot_id: str
    assessment_md: str = Field(
        description=(
            "Your assessment of this snapshot in the tenant's language: where the numbers stand, "
            "how the trajectory looks against the goal, what to change. Markdown, a few short "
            "paragraphs or bullets."
        )
    )


class MealUpdateIn(_In):
    meal_id: int
    name: str | None = None
    time: dt.time | None = None


class MealDeleteIn(_In):
    meal_id: int


class ProductUpdateIn(_In):
    product_id: int
    name: str | None = None
    brand: str | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None
    reference_amount: float | None = None
    reference_unit: Literal["g", "ml"] | None = None
    ean: str | None = None
    note: str | None = None
    source: str | None = Field(
        default=None,
        description="Where the values come from, e.g. 'label photo, capture <id>'. Always set it.",
    )


class ProductProposeIn(_In):
    product_id: int
    changes: dict[str, Any] = Field(
        description=(
            "Values read from the label per reference amount (100 g/ml): kcal, protein, carbs, "
            "fat, fiber, salt; optionally name, brand, ean, reference_unit, note."
        )
    )
    rationale: str | None = Field(default=None, description="One sentence: what you read where.")
    source: str | None = Field(default=None, description="e.g. 'label photo, capture <id>'.")
    capture_id: str | None = Field(default=None, description="The capture this comes from.")


class AgentRunStartIn(_In):
    #: "assess" records that this run judged frozen reports rather than drafting days.
    mode: Literal["historical", "batch", "manual", "follow_up", "assess"] = "historical"
    dates: list[dt.date] | None = Field(
        default=None, description="Explicit days to lock; otherwise days with open captures."
    )
    captures: list[str] | None = None


class AgentRunFinishIn(_In):
    run_id: str
    summary: str | None = Field(default=None, description="Markdown summary shown to the user.")
    status: Literal["finished", "budget_exceeded", "failed", "cancelled"] = "finished"
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error: str | None = None


class DraftCreateIn(BaseModel):
    """Loose pydantic shell; the real validation is the agent-draft JSON schema."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    date: dt.date
    source_captures: list[str]
    meals: list[dict[str, Any]]
    training: Literal["rest", "strength", "martial_arts"] | None = None
    notes: list[str] | None = None
    open_questions: list[str] | None = None
    prompt_version: str | None = None


class DraftDiscardIn(_In):
    date: dt.date


class CorrectionIn(_In):
    line_item_id: int
    amount: float | None = None
    unit_code: str | None = None
    consumable_id: int | None = None
    delete: bool = False


class DayApproveIn(_In):
    date: dt.date
    corrections: list[CorrectionIn] = Field(default_factory=list)
    close: bool = Field(
        default=True, description="Close the day (counts for TDEE) or keep it open."
    )


class LineItemCreateIn(_In):
    date: dt.date
    meal: str = Field(description="Meal name; created when the day has no meal with this name.")
    consumable_id: int
    amount: float = Field(gt=0)
    unit_code: str = "g"
    estimated: bool = False
    amount_estimated: bool = False
    raw_text: str | None = None


class LineItemUpdateIn(_In):
    line_item_id: int
    amount: float | None = None
    unit_code: str | None = None
    consumable_id: int | None = None
    portion_id: int | None = None
    estimated: bool | None = None
    amount_estimated: bool | None = None


class LineItemDeleteIn(_In):
    line_item_id: int


class RulesListIn(_In):
    scope: Literal["products", "days", "reports", "all"] | None = None


class RuleUpsertIn(_In):
    when: str = Field(description="What the rule applies to, e.g. 'bread rolls from the bakery'.")
    then: str = Field(description="What to do then, e.g. 'take the values from their own site'.")
    name: str | None = Field(
        default=None, description="Short name; derived from `when` if omitted."
    )
    scope: Literal["products", "days", "reports", "all"] = "all"
    enabled: bool = True
    priority: int = Field(default=100, description="Lower comes first.")


class RuleDeleteIn(_In):
    name: str


class ProductUsageIn(_In):
    product_id: int
    limit: int = Field(default=50, ge=1, le=500)


class ProductPortionIn(_In):
    """A count portion offered with a new product (the tub, can or slice it comes in)."""

    unit_code: str = Field(description="Count unit code, e.g. 'piece', 'slice', 'cup', 'can'.")
    label: str | None = None
    amount: float = Field(gt=0, description="Weight/volume of one unit in amount_unit.")
    amount_unit: Literal["g", "ml"] = "g"
    is_default: bool = False


class ProductCreateIn(_In):
    name: str
    brand: str | None = None
    category: str | None = None
    reference_amount: float = 100.0
    reference_unit: Literal["g", "ml"] = "g"
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None
    source: str | None = Field(
        default=None, description="Where the values come from (label, site)."
    )
    note: str | None = None
    ean: str | None = None
    portions: list[ProductPortionIn] | None = Field(
        default=None,
        description="Portions to create with the product, e.g. the 400 g tub it is sold in.",
    )
    capture_id: str | None = Field(
        default=None, description="The capture the values were read from (label photo, note)."
    )
    rationale: str | None = Field(
        default=None, description="Why these values — the person reviewing reads this."
    )


class PortionCreateIn(_In):
    product_id: int
    unit_code: str = Field(description="Count unit code, e.g. 'piece', 'slice', 'cup'.")
    label: str
    amount: float = Field(gt=0, description="Weight/volume of one unit in amount_unit.")
    amount_unit: Literal["g", "ml"] = "g"
    is_default: bool = False


class PortionUpdateIn(_In):
    portion_id: int = Field(description="The portion to correct, from the product's portions.")
    unit_code: str | None = Field(
        default=None, description="Corrected count unit, e.g. 'ball' where 'piece' was wrong."
    )
    label: str | None = None
    description: str | None = None
    amount: float | None = Field(
        default=None, gt=0, description="Corrected weight/volume of one unit."
    )
    amount_unit: Literal["g", "ml"] | None = None
    is_default: bool | None = None
    rationale: str | None = Field(
        default=None, description="One sentence: what is wrong and how you know."
    )


class PortionDeleteIn(_In):
    portion_id: int
    reason: str = Field(
        description="Why it should go, e.g. 'duplicates the 250 g pouch in the right unit'."
    )
    rationale: str | None = None


class WeightAddIn(_In):
    measured_at: dt.datetime = Field(description="Timestamp of the measurement (ISO 8601).")
    kg: float


# ── helpers ─────────────────────────────────────────────────────────────────


def _require(tc: ToolContext, scope: str) -> None:
    if not tc.ctx.has_scope(scope):
        raise ToolError("forbidden", f"scope '{scope}' required")


def _timezone(tc: ToolContext) -> str:
    """The tenant's zone, so a day means the same thing here as in the app (R69)."""
    fallback = Regional(tc.config.regional.timezone, tc.config.regional.locale)
    with tc.uow_factory(tc.ctx) as uow:
        return regional_of(uow, fallback).timezone


def _compact_product(p: Any) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "kcal_per_100": p.kcal,
        "protein_per_100": p.protein,
        "reference_unit": p.reference_unit,
        "portions": [
            {
                "id": po.id,
                "unit_code": po.unit_code,
                "label": po.label,
                "amount": po.amount,
                "amount_unit": po.amount_unit,
                "is_default": po.is_default,
            }
            for po in p.portions
        ],
    }


def _render_report(tc: ToolContext, inp: ReportRenderIn) -> ToolResult:
    registry = ReportRegistry()
    try:
        definition = registry.get(inp.name)
    except KeyError as exc:
        raise ToolError("not_found", f"unknown report '{inp.name}'") from exc
    tz = _timezone(tc)
    today = inp.as_of or today_in(tz)
    if inp.from_ and inp.to:
        if inp.to < inp.from_:
            raise ToolError("validation", "'to' lies before 'from'")
        period = Period(inp.from_, inp.to)
    elif inp.period:
        try:
            period = parse_period_token(inp.period, today)
        except ValueError as exc:
            raise ToolError("validation", str(exc)) from exc
    else:
        period = definition.default_period(today)
    with tc.uow_factory(tc.ctx) as uow:
        source = SqlAlchemyReportDataSource(cast(SqlAlchemyUnitOfWork, uow), tz)
        result = ReportEngine(source).render(definition, period, today=today)
    if inp.format == "json":
        return to_dict(result)
    return to_markdown(result)


def _locked_days(tc: ToolContext) -> set[date] | None:
    if tc.run_id is None:
        return None
    with tc.uow_factory(tc.ctx) as uow:
        run = uow.agent.get_run(tc.run_id)
        if run is None:
            return set()
        return {date.fromisoformat(d) for d in (run.days or [])}


# ── handlers ────────────────────────────────────────────────────────────────


def _product_search(tc: ToolContext, inp: ProductSearchIn) -> ToolResult:
    matches = product_uc.MatchText(tc.uow_factory, tc.ctx).execute(inp.q, limit=inp.limit)
    products = product_uc.SearchProducts(tc.uow_factory, tc.ctx).execute(
        inp.q, limit=inp.limit, on=inp.on
    )
    return {
        "query": inp.q,
        "matches": [jsonable(m) for m in matches],
        "products": [_compact_product(p) for p in products],
    }


def _body_measurements(tc: ToolContext, inp: BodyMeasurementsIn) -> ToolResult:
    rows = body_uc.ListBodyMeasurements(tc.uow_factory, tc.ctx).execute(limit=inp.limit)
    return {"measurements": [jsonable(r) for r in rows]}


def _body_add(tc: ToolContext, inp: BodyAddIn) -> ToolResult:
    view = body_uc.AddBodyMeasurement(tc.uow_factory, tc.ctx).execute(
        body_uc.BodyInput(**inp.model_dump())
    )
    return cast(ToolResult, jsonable(view))


def _product_versions(tc: ToolContext, inp: ProductVersionsIn) -> ToolResult:
    rows = product_uc.ProductVersions(tc.uow_factory, tc.ctx).execute(inp.id)
    return {"product_id": inp.id, "versions": [jsonable(p) for p in rows]}


def _product_version_create(tc: ToolContext, inp: ProductVersionCreateIn) -> ToolResult:
    fresh = product_uc.NewProductVersion(tc.uow_factory, tc.ctx).execute(
        inp.id, inp.valid_from, inp.changes
    )
    return cast(ToolResult, jsonable(fresh))


def _product_get(tc: ToolContext, inp: ProductGetIn) -> ToolResult:
    return cast(
        dict[str, Any], jsonable(product_uc.GetProduct(tc.uow_factory, tc.ctx).execute(inp.id))
    )


def _recipe_get(tc: ToolContext, inp: RecipeGetIn) -> ToolResult:
    return cast(
        dict[str, Any], jsonable(recipe_uc.GetRecipe(tc.uow_factory, tc.ctx).execute(inp.id))
    )


def _day_get(tc: ToolContext, inp: DayGetIn) -> ToolResult:
    return cast(dict[str, Any], jsonable(day_uc.GetDay(tc.uow_factory, tc.ctx).execute(inp.date)))


def _days_list(tc: ToolContext, inp: DaysListIn) -> ToolResult:
    rows = day_uc.ListDays(tc.uow_factory, tc.ctx).execute(inp.from_, inp.to, inp.status)
    return cast(list[Any], jsonable(rows))


def _drafts_list(tc: ToolContext, _inp: NoArgsIn) -> ToolResult:
    return cast(list[Any], jsonable(draft_uc.ListDrafts(tc.uow_factory, tc.ctx).execute()))


def _day_thread_get(tc: ToolContext, inp: DayThreadGetIn) -> ToolResult:
    view = agent_uc.GetDayContext(tc.uow_factory, tc.ctx).execute(
        inp.date, include_processed=inp.include_processed
    )
    return cast(dict[str, Any], jsonable(view))


def _day_message_add(tc: ToolContext, inp: DayMessageAddIn) -> ToolResult:
    view = day_uc.AddDayMessage(tc.uow_factory, tc.ctx).execute(inp.date, inp.text)
    return cast(dict[str, Any], jsonable(view))


def _agent_message_add(tc: ToolContext, inp: AgentMessageAddIn) -> ToolResult:
    view = agent_uc.AddAgentMessage(tc.uow_factory, tc.ctx).execute(
        inp.run_id, inp.date, inp.kind, inp.content
    )
    return cast(dict[str, Any], jsonable(view))


def _draft_summary(tc: ToolContext, inp: DraftSummaryIn) -> ToolResult:
    view = draft_uc.DraftSummary(tc.uow_factory, tc.ctx).execute(inp.date)
    return {"date": inp.date.isoformat(), "markdown": view.markdown, "day": jsonable(view.day)}


def _captures_open(tc: ToolContext, inp: CapturesOpenIn) -> ToolResult:
    rows = capture_uc.ListCaptures(tc.uow_factory, tc.ctx).execute(
        status=CaptureStatus.NEW.value, target_date=inp.date
    )
    if inp.scope == "product":
        rows = [c for c in rows if c.product_id is not None]
    elif inp.scope == "day":
        rows = [c for c in rows if c.product_id is None]
        scope_days = _locked_days(tc)
        if scope_days is not None and inp.date is None:
            rows = [c for c in rows if c.target_date in scope_days]
    return cast(list[Any], jsonable(rows))


def _capture_get(tc: ToolContext, inp: CaptureGetIn) -> ToolResult:
    cap = capture_uc.GetCapture(tc.uow_factory, tc.ctx).execute(inp.id)
    if cap.kind == CaptureKind.AUDIO.value and cap.transcript is None and tc.transcription:
        if tc.blobs is None:
            raise ToolError("unavailable", "blob storage is not configured")
        cap = capture_uc.TranscribeCapture(
            tc.uow_factory, tc.ctx, tc.blobs, tc.transcription
        ).execute(inp.id)
    image_ids = [a.id for a in cap.attachments if a.mime.startswith("image/")]
    if not image_ids and cap.kind == CaptureKind.IMAGE.value and cap.attachment_id:
        image_ids = [cap.attachment_id]
    if image_ids:
        if tc.blobs is None:
            raise ToolError("unavailable", "blob storage is not configured")
        wanted = inp.attachment_id or image_ids[0]
        att = capture_uc.GetAttachment(tc.uow_factory, tc.ctx, tc.blobs).execute(wanted)
        caption = json.dumps(jsonable(cap))
        return ImageResult(
            data_b64=base64.b64encode(att.data).decode("ascii"), mime=att.mime, text=caption
        )
    return cast(dict[str, Any], jsonable(cap))


def _capture_mark(tc: ToolContext, inp: CaptureMarkIn) -> ToolResult:
    changes: dict[str, Any] = {}
    if inp.status is not None:
        changes["status"] = inp.status
    if "target_date" in inp.model_fields_set:
        changes["target_date"] = inp.target_date
    if "product_id" in inp.model_fields_set:
        changes["product_id"] = inp.product_id
    view = capture_uc.UpdateCapture(tc.uow_factory, tc.ctx).execute(inp.id, changes)
    return cast(dict[str, Any], jsonable(view))


def _agent_run_start(tc: ToolContext, inp: AgentRunStartIn) -> ToolResult:
    view = agent_uc.BeginAgentRun(tc.uow_factory, tc.ctx).execute(
        runner="external",
        mode=inp.mode,
        dates=inp.dates,
        captures=inp.captures,
        lock_ttl_minutes=tc.config.agent.lock_ttl_minutes,
    )
    return {
        "run_id": view.run.id,
        "locked_days": [d.isoformat() for d in view.locked_days],
        "skipped_days": {d.isoformat(): why for d, why in view.skipped_days.items()},
        "run": jsonable(view.run),
    }


def _agent_run_finish(tc: ToolContext, inp: AgentRunFinishIn) -> ToolResult:
    view = agent_uc.FinishAgentRun(tc.uow_factory, tc.ctx).execute(
        inp.run_id,
        status=inp.status,
        summary_md=inp.summary,
        error=inp.error,
        input_tokens=inp.input_tokens,
        output_tokens=inp.output_tokens,
        cost_usd=inp.cost_usd,
    )
    return cast(dict[str, Any], jsonable(view))


def _draft_create(tc: ToolContext, inp: DraftCreateIn) -> ToolResult:
    draft = inp.model_dump(mode="json", exclude_none=True)
    view = agent_uc.CreateDraft(tc.uow_factory, tc.ctx).execute(draft)
    return cast(dict[str, Any], jsonable(view))


def _draft_discard(tc: ToolContext, inp: DraftDiscardIn) -> ToolResult:
    removed = draft_uc.DiscardDraft(tc.uow_factory, tc.ctx).execute(inp.date)
    return {"date": inp.date.isoformat(), "discarded_items": removed}


def _day_approve(tc: ToolContext, inp: DayApproveIn) -> ToolResult:
    corrections = [
        draft_uc.DraftCorrection(
            line_item_id=c.line_item_id,
            amount=c.amount,
            unit_code=c.unit_code,
            consumable_id=c.consumable_id,
            delete=c.delete,
        )
        for c in inp.corrections
    ]
    view = draft_uc.ApproveDay(tc.uow_factory, tc.ctx).execute(
        inp.date, corrections, close=inp.close
    )
    return cast(dict[str, Any], jsonable(view))


def _line_item_create(tc: ToolContext, inp: LineItemCreateIn) -> ToolResult:
    day = day_uc.GetDay(tc.uow_factory, tc.ctx).execute(inp.date)
    meal = next((m for m in day.meals if m.name.strip().lower() == inp.meal.strip().lower()), None)
    meal_id = (
        meal.id
        if meal is not None
        else day_uc.AddMeal(tc.uow_factory, tc.ctx).execute(inp.date, inp.meal).id
    )
    view = day_uc.AddLineItem(tc.uow_factory, tc.ctx).execute(
        meal_id,
        day_uc.LineItemInput(
            consumable_id=inp.consumable_id,
            amount=inp.amount,
            unit_code=inp.unit_code,
            estimated=inp.estimated,
            amount_estimated=inp.amount_estimated,
            raw_text=inp.raw_text,
        ),
    )
    return cast(dict[str, Any], jsonable(view))


def _line_item_update(tc: ToolContext, inp: LineItemUpdateIn) -> ToolResult:
    changes = {k: v for k, v in inp.model_dump().items() if k != "line_item_id" and v is not None}
    view = day_uc.UpdateLineItem(tc.uow_factory, tc.ctx).execute(inp.line_item_id, changes)
    return cast(dict[str, Any], jsonable(view))


def _line_item_delete(tc: ToolContext, inp: LineItemDeleteIn) -> ToolResult:
    day_uc.DeleteLineItem(tc.uow_factory, tc.ctx).execute(inp.line_item_id)
    return {"deleted": inp.line_item_id}


def _line_item_approve(tc: ToolContext, inp: LineItemApproveIn) -> ToolResult:
    fields = inp.model_dump(exclude_none=True)
    fields.pop("line_item_id", None)
    meal_id = fields.pop("meal_id", None)
    meal_name = fields.pop("meal_name", None)
    correction = (
        draft_uc.DraftCorrection(line_item_id=inp.line_item_id, **fields) if fields else None
    )
    view = draft_uc.ApproveLineItem(tc.uow_factory, tc.ctx).execute(
        inp.line_item_id, correction, meal_id=meal_id, meal_name=meal_name
    )
    return cast(dict[str, Any], jsonable(view))


def _report_snapshot_create(tc: ToolContext, inp: ReportSnapshotCreateIn) -> ToolResult:
    definition = ReportRegistry().get(inp.name)
    tz = _timezone(tc)
    today = inp.as_of or today_in(tz)
    if inp.start and inp.end:
        period = Period(inp.start, inp.end)
    elif inp.period:
        period = parse_period_token(inp.period, today)
    else:
        period = definition.default_period(today)
    with tc.uow_factory(tc.ctx) as uow:
        source = SqlAlchemyReportDataSource(cast(SqlAlchemyUnitOfWork, uow), tz)
        result = ReportEngine(source).render(definition, period, today=today)
    payload = to_dict(result)
    payload["from"] = period.start.isoformat()
    payload["to"] = period.end.isoformat()
    payload["today"] = today.isoformat()
    view = snapshot_uc.FreezeReport(tc.uow_factory, tc.ctx).execute(
        definition.name,
        definition.title,
        payload,
        period_start=period.start,
        period_end=period.end,
        today=today,
        label=inp.label,
    )
    out = cast(dict[str, Any], jsonable(view))
    out["result"] = payload  # so the caller can assess without a second read
    return out


def _report_snapshots_list(tc: ToolContext, inp: ReportSnapshotsListIn) -> ToolResult:
    rows = snapshot_uc.ListSnapshots(tc.uow_factory, tc.ctx).execute(
        report_name=inp.report, limit=inp.limit
    )
    return cast(list[Any], jsonable(rows))


def _report_snapshot_get(tc: ToolContext, inp: ReportSnapshotGetIn) -> ToolResult:
    view = snapshot_uc.GetSnapshot(tc.uow_factory, tc.ctx).execute(inp.snapshot_id)
    return cast(dict[str, Any], jsonable(view))


def _report_assess(tc: ToolContext, inp: ReportAssessIn) -> ToolResult:
    view = snapshot_uc.AssessSnapshot(tc.uow_factory, tc.ctx).execute(
        inp.snapshot_id,
        inp.assessment_md,
        model=tc.config.agent.model if tc.config else None,
        prompt_version=tc.prompt_version or "external",
        run_id=tc.run_id,
    )
    return cast(dict[str, Any], jsonable(view))


def _meal_update(tc: ToolContext, inp: MealUpdateIn) -> ToolResult:
    changes = {k: v for k, v in inp.model_dump().items() if k != "meal_id" and v is not None}
    view = day_uc.UpdateMeal(tc.uow_factory, tc.ctx).execute(inp.meal_id, changes)
    return cast(dict[str, Any], jsonable(view))


def _meal_delete(tc: ToolContext, inp: MealDeleteIn) -> ToolResult:
    day_uc.DeleteMeal(tc.uow_factory, tc.ctx).execute(inp.meal_id)
    return {"deleted": inp.meal_id}


def _product_update(tc: ToolContext, inp: ProductUpdateIn) -> ToolResult:
    changes = {k: v for k, v in inp.model_dump().items() if k != "product_id" and v is not None}
    changes["verified"] = False  # a person confirms label readings in the review list
    view = proposal_uc.update_or_propose_product(
        tc.uow_factory, tc.ctx, inp.product_id, changes, run_id=tc.run_id
    )
    out = cast(dict[str, Any], jsonable(view))
    if isinstance(view, dto.ProductProposalView):
        out["pending_review"] = True
    return out


def _rules_list(tc: ToolContext, inp: RulesListIn) -> ToolResult:
    rows = rules_uc.ListRules(tc.uow_factory, tc.ctx).execute(scope=inp.scope)
    return cast(list[Any], jsonable(rows))


def _rule_upsert(tc: ToolContext, inp: RuleUpsertIn) -> ToolResult:
    view = rules_uc.UpsertRule(tc.uow_factory, tc.ctx).execute(
        rules_uc.RuleInput(**inp.model_dump())
    )
    return cast(dict[str, Any], jsonable(view))


def _rule_delete(tc: ToolContext, inp: RuleDeleteIn) -> ToolResult:
    rules_uc.DeleteRule(tc.uow_factory, tc.ctx).execute(inp.name)
    return {"deleted": inp.name}


def _product_usage(tc: ToolContext, inp: ProductUsageIn) -> ToolResult:
    view = product_uc.GetProductUsage(tc.uow_factory, tc.ctx).execute(
        inp.product_id, limit=inp.limit
    )
    return cast(dict[str, Any], jsonable(view))


def _product_propose(tc: ToolContext, inp: ProductProposeIn) -> ToolResult:
    view = proposal_uc.ProposeProductChange(tc.uow_factory, tc.ctx).execute(
        inp.product_id,
        inp.changes,
        rationale=inp.rationale,
        source=inp.source,
        capture_id=inp.capture_id,
        run_id=tc.run_id,
    )
    return cast(dict[str, Any], jsonable(view))


def _product_create(tc: ToolContext, inp: ProductCreateIn) -> ToolResult:
    fields = inp.model_dump()
    portions = fields.pop("portions", None)
    capture_id = fields.pop("capture_id", None)
    rationale = fields.pop("rationale", None)
    view = proposal_uc.create_or_propose_product(
        tc.uow_factory,
        tc.ctx,
        product_uc.ProductInput(**fields),
        portions=list(portions) if portions else None,  # model_dump already nested them
        rationale=rationale,
        capture_id=capture_id,
        run_id=tc.run_id,
    )
    out = cast(dict[str, Any], jsonable(view))
    if isinstance(view, dto.ProductProposalView):
        # The catalogue entry waits for a person; the one-off carries the values today.
        out["pending_review"] = True
        out["log_against_consumable_id"] = view.consumable_id
    return out


def _portion_create(tc: ToolContext, inp: PortionCreateIn) -> ToolResult:
    view = proposal_uc.add_or_propose_portion(
        tc.uow_factory,
        tc.ctx,
        inp.product_id,
        {
            "unit_code": inp.unit_code,
            "label": inp.label,
            "amount": inp.amount,
            "amount_unit": inp.amount_unit,
            "is_default": inp.is_default,
        },
        run_id=tc.run_id,
    )
    out = cast(dict[str, Any], jsonable(view))
    if isinstance(view, dto.ProductProposalView):
        out["pending_review"] = True
    return out


def _portion_update(tc: ToolContext, inp: PortionUpdateIn) -> ToolResult:
    fields = inp.model_dump(exclude_none=True)
    portion_id = int(fields.pop("portion_id"))
    rationale = fields.pop("rationale", None)
    view = proposal_uc.update_or_propose_portion(
        tc.uow_factory, tc.ctx, portion_id, fields, rationale=rationale, run_id=tc.run_id
    )
    out = cast(dict[str, Any], jsonable(view))
    if isinstance(view, dto.ProductProposalView):
        out["pending_review"] = True
    return out


def _portion_delete(tc: ToolContext, inp: PortionDeleteIn) -> ToolResult:
    view = proposal_uc.delete_or_propose_portion(
        tc.uow_factory,
        tc.ctx,
        inp.portion_id,
        reason=inp.reason,
        rationale=inp.rationale or inp.reason,
        run_id=tc.run_id,
    )
    if view is None:
        return {"deleted": inp.portion_id}
    out = cast(dict[str, Any], jsonable(view))
    out["pending_review"] = True
    return out


def _weight_add(tc: ToolContext, inp: WeightAddIn) -> ToolResult:
    view = weight_uc.AddManualWeight(tc.uow_factory, tc.ctx).execute(inp.measured_at, inp.kg)
    return cast(dict[str, Any], jsonable(view))


def _draft_schema() -> dict[str, Any]:
    schema = dict(load_schema("agent-draft"))
    for key in ("$schema", "$id", "examples"):
        schema.pop(key, None)
    return schema


# ── registry ────────────────────────────────────────────────────────────────


def _spec(
    name: str,
    description: str,
    scope: str,
    model: type[BaseModel],
    handler: Callable[[ToolContext, Any], ToolResult],
    *,
    read_only: bool = True,
    override: dict[str, Any] | None = None,
) -> ToolSpec:
    return ToolSpec(name, description, scope, model, handler, read_only, override)


TOOLS: tuple[ToolSpec, ...] = (
    _spec(
        "product_search",
        "Find products for a free-text food item. Returns matcher candidates (tier 1 exact, "
        "2 short form, 3 fuzzy; score 0–1) and matching products with portions and kcal/100. "
        "Call this for every item before choosing a consumable or creating a product.",
        SCOPE_READ,
        ProductSearchIn,
        _product_search,
    ),
    _spec(
        "product_get",
        "A product with nutrients per 100 g/ml and its portions.",
        SCOPE_READ,
        ProductGetIn,
        _product_get,
    ),
    _spec(
        "body_measurements",
        "Recent tape-measure sessions with waist, hip, belly and the rest, newest first. "
        "Read this before adding one, so an existing session is corrected rather than doubled.",
        SCOPE_READ,
        BodyMeasurementsIn,
        _body_measurements,
    ),
    _spec(
        "body_add",
        "Record a tape-measure session from a note, a photo of a tape or a spoken list, e.g. "
        '"waist 126, hip 118". Centimetres, and only the values actually given: a missing '
        "circumference must stay empty rather than be guessed, because the ratios built on it "
        "would then be wrong. Weight does not belong here, use weight_add.",
        SCOPE_WRITE,
        BodyAddIn,
        _body_add,
        read_only=False,
    ),
    _spec(
        "product_versions",
        "Every version of a product, oldest first, with the days each one covers. Use it when "
        "the values of a food changed over time and you need to know which numbers held when.",
        SCOPE_READ,
        ProductVersionsIn,
        _product_versions,
    ),
    _spec(
        "product_version_create",
        "Record that a product's values changed from a day on. The previous version keeps its "
        "numbers and is closed the day before, so days already logged are untouched; the new "
        "one starts open ended. Use this instead of product_update when the food itself "
        "changed, for example a reformulated recipe or a different supplier.",
        SCOPE_WRITE,
        ProductVersionCreateIn,
        _product_version_create,
        read_only=False,
    ),
    _spec(
        "recipe_get",
        "A recipe with ingredients and cooked batches.",
        SCOPE_READ,
        RecipeGetIn,
        _recipe_get,
    ),
    _spec(
        "day_get",
        "One day: meals, line items, computed macros, target band, findings.",
        SCOPE_READ,
        DayGetIn,
        _day_get,
    ),
    _spec(
        "days_list",
        "Compact list of days in a range with macros and status.",
        SCOPE_READ,
        DaysListIn,
        _days_list,
    ),
    _spec(
        "drafts_list",
        "Days that currently have draft items awaiting approval.",
        SCOPE_READ,
        NoArgsIn,
        _drafts_list,
    ),
    _spec(
        "day_thread_get",
        "The day's thread: current day (draft or approved), earlier messages, and open captures "
        "with transcripts. Seed every drafting session with this.",
        SCOPE_READ,
        DayThreadGetIn,
        _day_thread_get,
    ),
    _spec(
        "day_message_add",
        "Add a user message to a day's thread (queues a follow-up run when the day is drafted "
        "or locked).",
        SCOPE_WRITE,
        DayMessageAddIn,
        _day_message_add,
        read_only=False,
    ),
    _spec(
        "agent_message_add",
        "Write your own message into a day's thread without drafting: 'summary' is the day's "
        "verdict shown above its meals (two or three sentences, see the day_verdict prompt) "
        "and replaces the previous one, 'note', 'question' and 'correction' accumulate.",
        SCOPE_AGENT_WRITE,
        AgentMessageAddIn,
        _agent_message_add,
        read_only=False,
    ),
    _spec(
        "draft_summary",
        "Markdown + JSON summary of a drafted day for the approval dialogue.",
        SCOPE_READ,
        DraftSummaryIn,
        _draft_summary,
    ),
    _spec(
        "report_render",
        "Render a report (default 'checkup') for a period token like '14d' or explicit "
        "from/to dates.",
        SCOPE_READ,
        ReportRenderIn,
        _render_report,
    ),
    _spec(
        "captures_open",
        "Captures with status=new. Inside a run this is scoped to the run's locked days.",
        SCOPE_CAPTURE_READ,
        CapturesOpenIn,
        _captures_open,
    ),
    _spec(
        "capture_get",
        "One capture: text, transcript (audio is transcribed on demand) or the image itself.",
        SCOPE_CAPTURE_READ,
        CaptureGetIn,
        _capture_get,
    ),
    _spec(
        "capture_mark",
        "Change a capture's status or target day (e.g. assign an undated voice note to a day).",
        SCOPE_CAPTURE_WRITE,
        CaptureMarkIn,
        _capture_mark,
        read_only=False,
    ),
    _spec(
        "agent_run_start",
        "Start an external agent run: locks the days in scope and returns run_id plus "
        "locked/skipped days. Days locked by another run are skipped, never waited for.",
        SCOPE_AGENT_WRITE,
        AgentRunStartIn,
        _agent_run_start,
        read_only=False,
    ),
    _spec(
        "agent_run_finish",
        "Finish a run: stores the summary and usage, releases every lock the run holds.",
        SCOPE_AGENT_WRITE,
        AgentRunFinishIn,
        _agent_run_finish,
        read_only=False,
    ),
    _spec(
        "draft_create",
        "Write one day's draft (meals with line items: candidates, quantity, confidence, "
        "rationale, source capture). Requires the live lock held by run_id; validated against "
        "agent-draft.schema.json.",
        SCOPE_AGENT_WRITE,
        DraftCreateIn,
        _draft_create,
        read_only=False,
        override=_draft_schema(),
    ),
    _spec(
        "draft_discard",
        "Remove all draft items of a day.",
        SCOPE_APPROVE,
        DraftDiscardIn,
        _draft_discard,
        read_only=False,
    ),
    _spec(
        "day_approve",
        "Approve a drafted day: apply corrections, clear draft flags, freeze the target band, "
        "mark captures processed.",
        SCOPE_APPROVE,
        DayApproveIn,
        _day_approve,
        read_only=False,
    ),
    _spec(
        "line_item_create",
        "Add a line item to a meal of a day (meal created when missing). Without the "
        "approve scope it is added as a draft for review — the same gate as a drafted "
        "item, so nothing you write becomes a fact on its own.",
        SCOPE_WRITE,
        LineItemCreateIn,
        _line_item_create,
        read_only=False,
    ),
    _spec(
        "line_item_update",
        "Change amount, unit, portion or consumable of a line item. Drafts only: "
        "changing an approved item needs the approve scope.",
        SCOPE_WRITE,
        LineItemUpdateIn,
        _line_item_update,
        read_only=False,
    ),
    _spec(
        "line_item_delete",
        "Delete a line item. You may withdraw your own draft; removing an approved item "
        "needs the approve scope.",
        SCOPE_WRITE,
        LineItemDeleteIn,
        _line_item_delete,
        read_only=False,
    ),
    _spec(
        "report_snapshot_create",
        "Freeze a report as a snapshot: the numbers of that period, stored with today's date. "
        "Returns the frozen result so you can assess it right away with report_assess.",
        SCOPE_READ,
        ReportSnapshotCreateIn,
        _report_snapshot_create,
        read_only=False,
    ),
    _spec(
        "report_snapshots_list",
        "Snapshots, newest first, with their assessment status.",
        SCOPE_READ,
        ReportSnapshotsListIn,
        _report_snapshots_list,
    ),
    _spec(
        "report_snapshot_get",
        "One snapshot with its frozen numbers and its assessment.",
        SCOPE_READ,
        ReportSnapshotGetIn,
        _report_snapshot_get,
    ),
    _spec(
        "report_assess",
        "Write your assessment of a frozen snapshot. The numbers stay as they were; a snapshot "
        "carries exactly one assessment.",
        SCOPE_AGENT_WRITE,
        ReportAssessIn,
        _report_assess,
        read_only=False,
    ),
    _spec(
        "line_item_approve",
        "Accept one drafted line item (optionally correcting amount, unit or product). "
        "The rest of the day stays a draft.",
        SCOPE_APPROVE,
        LineItemApproveIn,
        _line_item_approve,
        read_only=False,
    ),
    _spec(
        "meal_update",
        "Rename a meal or change its time.",
        SCOPE_WRITE,
        MealUpdateIn,
        _meal_update,
        read_only=False,
    ),
    _spec(
        "meal_delete",
        "Delete an empty meal (fails while it still has line items).",
        SCOPE_WRITE,
        MealDeleteIn,
        _meal_delete,
        read_only=False,
    ),
    _spec(
        "rules_list",
        "The user's own instructions for you (when → then). Read them before deciding where a "
        "value comes from.",
        SCOPE_READ,
        RulesListIn,
        _rules_list,
    ),
    _spec(
        "rule_upsert",
        "Write down a rule the user just gave you, e.g. \"for bread rolls check the bakery's own "
        'site". Replaces the rule with the same name; creates a settings version.',
        SCOPE_WRITE,
        RuleUpsertIn,
        _rule_upsert,
        read_only=False,
    ),
    _spec(
        "rule_delete",
        "Remove one of the user's rules by name.",
        SCOPE_WRITE,
        RuleDeleteIn,
        _rule_delete,
        read_only=False,
    ),
    _spec(
        "product_usage",
        "The days a product was logged on, newest first, with amounts and kcal.",
        SCOPE_READ,
        ProductUsageIn,
        _product_usage,
    ),
    _spec(
        "product_propose",
        "Propose corrected product values read from a label photo or note. A person approves "
        "in the app; nothing changes until then. Use this for product captures. `changes` may "
        "also carry a `portions` list whose entries say what they do: {'op': 'add', "
        "'unit_code': …, 'amount': …}, {'op': 'update', 'portion_id': …, …} or {'op': 'delete', "
        "'portion_id': …, 'reason': …}.",
        SCOPE_AGENT_WRITE,
        ProductProposeIn,
        _product_propose,
        read_only=False,
    ),
    _spec(
        "product_update",
        "Correct a product's nutrients per reference amount, e.g. from a label photo capture. "
        "Without the approve scope it becomes a proposal a person decides; with it, values "
        "propagate to every logged quantity of that product. Set `source`.",
        SCOPE_WRITE,
        ProductUpdateIn,
        _product_update,
        read_only=False,
    ),
    _spec(
        "product_create",
        "Register a product with nutrients per reference amount (100 g/ml), optionally "
        "with its portions. Without the approve scope this does not touch the catalogue: "
        "it files a pending proposal and returns `log_against_consumable_id`, which you "
        "use in the day draft right away. Approving it in the app turns that one-off into "
        "the catalogue entry, keeping every item already logged against it.",
        SCOPE_WRITE,
        ProductCreateIn,
        _product_create,
        read_only=False,
    ),
    _spec(
        "portion_create",
        "Add a count portion (piece, slice, cup…) with its weight to a product. Without the "
        "approve scope it becomes a proposal a person decides.",
        SCOPE_WRITE,
        PortionCreateIn,
        _portion_create,
        read_only=False,
    ),
    _spec(
        "portion_update",
        "Correct an existing portion — the wrong count unit, a wrong weight, a better label. "
        "Adding the corrected portion instead leaves the wrong row in place, and where the "
        "unit is what was wrong it is refused as a duplicate. Without the approve scope this "
        "becomes a proposal a person decides.",
        SCOPE_WRITE,
        PortionUpdateIn,
        _portion_update,
        read_only=False,
    ),
    _spec(
        "portion_delete",
        "Remove a portion that should not exist — a duplicate in the wrong unit, a size no "
        "such thing can have. Say why in `reason`: the person reviewing sees it next to the "
        "row and how many logged items use it. Without the approve scope this becomes a "
        "proposal; a portion still in use cannot be removed at all.",
        SCOPE_WRITE,
        PortionDeleteIn,
        _portion_delete,
        read_only=False,
    ),
    _spec(
        "weight_add",
        "Record a manual body-weight measurement.",
        SCOPE_WRITE,
        WeightAddIn,
        _weight_add,
        read_only=False,
    ),
)

_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}

# Tools a drafting session may use (R49: the worker never approves).
WORKER_TOOLS: frozenset[str] = frozenset(
    {
        "product_search",
        "product_get",
        "product_versions",
        "body_measurements",
        "body_add",
        "weight_add",
        "recipe_get",
        "day_get",
        "days_list",
        "day_thread_get",
        "report_render",
        "rules_list",
        "report_snapshot_create",
        "report_assess",
        "captures_open",
        "capture_get",
        "capture_mark",
        "agent_message_add",
        "draft_create",
        "product_create",
        "product_propose",
        "portion_create",
        "portion_update",
        "portion_delete",
    }
)


def get_tool(name: str) -> ToolSpec:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise ToolError("unknown_tool", f"unknown tool '{name}'") from exc


def tools_for(ctx: TenantContext, names: frozenset[str] | None = None) -> list[ToolSpec]:
    """Tools the context may call (by scope), optionally restricted to ``names``."""
    return [t for t in TOOLS if ctx.has_scope(t.scope) and (names is None or t.name in names)]


def dispatch(tc: ToolContext, name: str, arguments: dict[str, Any] | None) -> ToolResult:
    """Validate arguments, check the scope, run the handler; errors become ToolError."""
    spec = get_tool(name)
    _require(tc, spec.scope)
    try:
        inp = spec.input_model.model_validate(arguments or {})
    except ValidationError as exc:
        details = "; ".join(
            f"{'/'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8]
        )
        raise ToolError("validation", f"invalid arguments for {name}: {details}") from exc
    try:
        return spec.handler(tc, inp)
    except ScopeError as exc:
        raise ToolError("forbidden", str(exc)) from exc
    except ApplicationError as exc:
        code = type(exc).__name__
        extra = f" ({exc.errors})" if exc.errors else ""
        raise ToolError(code, f"{exc.detail}{extra}") from exc


def anthropic_tool_definitions(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    """Anthropic ``tools`` parameter for the given specs (strict where the schema allows)."""
    out: list[dict[str, Any]] = []
    for spec in specs:
        schema = spec.input_schema()
        entry: dict[str, Any] = {
            "name": spec.name,
            "description": spec.description,
            "input_schema": schema,
        }
        if spec.input_schema_override is None and "$defs" not in schema:
            entry["strict"] = True
            _strictify(schema)
        out.append(entry)
    return out


def _strictify(schema: dict[str, Any]) -> None:
    """Strict tool use needs additionalProperties:false and every property required."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        schema["required"] = list(props)
        for prop in props.values():
            if isinstance(prop, dict):
                _strictify(prop)
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []) or []:
            if isinstance(sub, dict):
                _strictify(sub)
    items = schema.get("items")
    if isinstance(items, dict):
        _strictify(items)


def result_text(result: ToolResult) -> str:
    """Serialise a tool result as the text a model reads."""
    if isinstance(result, ImageResult):
        return result.text
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


__all__ = [
    "TOOLS",
    "WORKER_TOOLS",
    "ImageResult",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "ToolSpec",
    "anthropic_tool_definitions",
    "dispatch",
    "get_tool",
    "jsonable",
    "result_text",
    "tools_for",
]
