"""Result objects of the use cases — framework-free, serialised by the API layer.

Field names mirror ``docs/API.md`` and the web client's ``models.ts`` so the
Pydantic response schemas can be built with ``from_attributes``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from victus.domain.values import BandZone, Finding, Macros, MatchCandidate

# ── master data ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class UnitView:
    code: str
    singular: str
    plural: str
    unit_type: str


@dataclass(frozen=True, slots=True)
class CategoryView:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class PortionView:
    id: int
    product_id: int
    unit_code: str
    label: str
    description: str | None
    amount: float
    amount_unit: str
    is_default: bool
    weight_source: str | None


@dataclass(frozen=True, slots=True)
class ProductView:
    id: int
    name: str
    icon: str | None
    brand: str | None
    category_id: int | None
    category: str | None
    reference_amount: float
    reference_unit: str
    kcal: float | None
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    salt: float | None
    source: str | None
    verified: bool
    ean: str | None
    note: str | None
    #: Validity of these values; ``valid_until`` None means the product is current (R70).
    valid_from: date | None = None
    valid_until: date | None = None
    #: The version this one replaced, if any.
    supersedes_id: int | None = None
    portions: list[PortionView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IngredientView:
    id: int
    position: int
    product_id: int | None
    product_name: str | None
    amount: float | None
    unit_code: str | None
    free_text: str | None


@dataclass(frozen=True, slots=True)
class BatchView:
    id: int
    recipe_id: int
    name: str
    cooked_at: date | None
    servings: int | None
    total_weight_g: float | None
    kcal: float | None
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    salt: float | None
    finished_at: date | None


@dataclass(frozen=True, slots=True)
class RecipeView:
    id: int
    name: str
    default_servings: int | None
    ingredients: list[IngredientView] = field(default_factory=list)
    batches: list[BatchView] = field(default_factory=list)


# ── days ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LineItemView:
    id: int
    meal_id: int
    position: int
    consumable_id: int
    consumable_name: str
    consumable_kind: str
    amount: float | None
    unit_code: str | None
    #: The portion this amount was resolved through, and its label — one unit can have
    #: several (a piece of egg is S, M, L or XL), and the unit alone cannot say which.
    portion_id: int | None
    portion_label: str | None
    base_amount: float
    base_unit: str
    estimated: bool
    amount_estimated: bool
    is_draft: bool
    confidence: float | None
    rationale: str | None
    alternatives: list[dict[str, Any]] | None
    raw_text: str | None
    source_capture_id: str | None
    source_kind: str | None
    category: str | None
    icon: str | None
    kcal: float | None
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    salt: float | None


@dataclass(frozen=True, slots=True)
class MealView:
    id: int
    position: int
    name: str
    time: dt.time | None
    line_items: list[LineItemView]
    totals: Macros


@dataclass(frozen=True, slots=True)
class BandSpecView:
    min: float
    opt_min: float
    opt_max: float
    target: float
    max: float
    stretch: float | None = None


@dataclass(frozen=True, slots=True)
class TargetBandView:
    id: int
    name: str
    training_type: str | None
    valid_from: date
    valid_until: date | None
    kcal: BandSpecView | None
    protein: BandSpecView
    carbs: BandSpecView
    fat: BandSpecView
    fiber: BandSpecView
    salt: BandSpecView
    note: str | None


@dataclass(frozen=True, slots=True)
class DaySummaryView:
    date: date
    status: str
    reliable: bool | None
    training_type: str | None
    macros: Macros
    has_drafts: bool
    weight_kg: float | None


@dataclass(frozen=True, slots=True)
class DayView:
    date: date
    status: str
    reliable: bool | None
    training_type: str | None
    macros: Macros
    has_drafts: bool
    weight_kg: float | None
    weekday: str | None
    meals: list[MealView]
    target_band: TargetBandView | None
    zones: dict[str, BandZone]
    findings: list[Finding]
    notes: str | None


@dataclass(frozen=True, slots=True)
class DayMessageView:
    id: str
    role: str
    kind: str
    content: str
    created_at: datetime
    processing_state: str | None
    # For messages that are captures: id, kind (text|audio|image) and media
    capture_id: str | None = None
    capture_kind: str | None = None
    attachment_id: str | None = None
    attachment_mime: str | None = None
    #: Every file of the capture. One capture can be two photos and a spoken note (R65),
    #: and `attachment_id` names only whichever arrived first.
    attachments: list[AttachmentRef] = field(default_factory=list)
    transcript: str | None = None


@dataclass(frozen=True, slots=True)
class DraftListEntryView:
    date: date
    status: str
    draft_items: int
    kcal: float | None
    estimated_items: int
    created_by: str


@dataclass(frozen=True, slots=True)
class DraftSummaryView:
    date: date
    markdown: str
    day: DayView


@dataclass(frozen=True, slots=True)
class WeightEntryView:
    id: int
    measured_at: datetime
    kg: float
    source: str


@dataclass(frozen=True, slots=True)
class BodyMeasurementView:
    """One tape-measure session; every circumference is optional (R76)."""

    id: int
    measured_at: datetime
    waist_cm: float | None = None
    belly_cm: float | None = None
    hip_cm: float | None = None
    chest_cm: float | None = None
    neck_cm: float | None = None
    thigh_cm: float | None = None
    arm_cm: float | None = None
    body_fat_pct: float | None = None
    note: str | None = None
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class SettingsVersionView:
    version: int
    valid_from: date
    data: dict[str, Any]
    changed_by: str | None


# ── auth ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class UserView:
    id: str
    display_name: str
    email: str | None
    role: str


@dataclass(frozen=True, slots=True)
class TenantView:
    id: str
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class MeView:
    user: UserView
    tenant: TenantView
    csrf_token: str
    passkeys: int
    recovery_session: bool = False


@dataclass(frozen=True, slots=True)
class PasskeyView:
    id: str
    name: str | None
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class TokenView:
    id: str
    name: str
    prefix: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class TokenCreatedView(TokenView):
    token: str = ""


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What the API layer needs after a successful login."""

    session_id: str
    tenant_id: str
    user_id: str
    expires_at: datetime
    recovery: bool = False


@dataclass(frozen=True, slots=True)
class OwnerCreated:
    user: UserView
    recovery_code: str


@dataclass(frozen=True, slots=True)
class HealthView:
    status: str
    version: str
    checks: dict[str, str]
    backup_age_hours: float | None


@dataclass(frozen=True, slots=True)
class MatchResult:
    candidates: list[MatchCandidate]


# ── captures, attachments, agent runs (Stage 3) ─────────────────────────────


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """One file of a capture."""

    id: str
    mime: str
    size: int
    original_name: str | None


@dataclass(frozen=True, slots=True)
class CaptureView:
    id: str
    kind: str
    captured_at: datetime
    target_date: date | None
    text: str | None
    status: str
    transcript: str | None
    attachment_id: str | None
    attachment_mime: str | None
    content_hash: str
    processed_at: datetime | None
    agent_run_id: str | None
    product_id: int | None = None  # set for captures about one product (label photo)
    attachments: list[AttachmentRef] = field(default_factory=list)
    created: bool = True  # False when the upload was a duplicate (content hash)


@dataclass(frozen=True, slots=True)
class ProductProposalView:
    id: str
    #: NULL while a ``new`` proposal is pending — the product does not exist yet.
    product_id: int | None
    product_name: str | None
    capture_id: str | None
    run_id: str | None
    changes: dict[str, Any]
    current: dict[str, Any]
    rationale: str | None
    source: str | None
    status: str
    created_at: datetime
    decided_at: datetime | None
    #: ``update`` (values of an existing product) or ``new`` (a product to be created).
    kind: str = "update"
    #: The one-off consumable a pending ``new`` proposal is logged against.
    consumable_id: int | None = None


@dataclass(frozen=True, slots=True)
class ProductUsageEntry:
    """One logged occurrence of a product, for its "where did I eat this" list."""

    date: date
    day_status: str
    meal: str
    line_item_id: int
    amount: float | None
    unit_code: str | None
    base_amount: float
    base_unit: str
    is_draft: bool
    estimated: bool
    kcal: float | None
    protein: float | None


@dataclass(frozen=True, slots=True)
class ProductUsage:
    product_id: int
    entries: list[ProductUsageEntry]
    days: int
    total_base_amount: float
    total_kcal: float
    first_date: date | None
    last_date: date | None


@dataclass(frozen=True, slots=True)
class RuleView:
    """One of the user's own instructions for the agent."""

    name: str
    when: str
    then: str
    scope: str
    enabled: bool
    priority: int


@dataclass(frozen=True, slots=True)
class ReportSnapshotView:
    id: str
    report_name: str
    title: str
    label: str | None
    period_start: date
    period_end: date
    today: date
    status: str
    created_at: datetime
    created_by: str | None
    assessment_md: str | None
    assessed_at: datetime | None
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    #: the frozen render, only when the detail was asked for
    result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AttachmentContent:
    id: str
    mime: str
    size: int
    original_name: str | None
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AgentSessionView:
    date: date
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    outcome: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class AgentRunView:
    id: str
    runner: str
    mode: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    captures: list[str]
    days: list[date]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str | None
    prompt_version: str | None
    summary_md: str | None
    error: str | None
    sessions: list[AgentSessionView] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class AgentLockView:
    date: date
    runner: str
    run_id: str
    locked_until: datetime


@dataclass(frozen=True, slots=True)
class RunStartView:
    """Result of taking a run from ``queued`` to ``running``: which days it holds."""

    run: AgentRunView
    locked_days: list[date]
    skipped_days: dict[date, str]


@dataclass(frozen=True, slots=True)
class DayContextView:
    """Everything one drafting session may see for its day (ADR 0009/0010)."""

    date: date
    day: DayView | None
    thread: list[DayMessageView]
    captures: list[CaptureView]
    locked_by_run_id: str | None


@dataclass(frozen=True, slots=True)
class DraftCreateView:
    date: date
    day: DayView
    created_items: int
    created_ad_hoc: int
    captures_assigned: int
    questions: int
    markdown: str
