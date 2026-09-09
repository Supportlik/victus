"""Typed results of a rendered report — one dataclass per block type.

Renderers (JSON for the web app, Markdown for chats) consume these; nothing in
here knows about HTTP or files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from victus.domain.model.reporting import (
    BandStat,
    BurndownResult,
    ForecastRow,
    RollingRow,
    TrendRow,
    WeekRow,
)
from victus.domain.values import (
    Band,
    BandZone,
    DayStatus,
    Macros,
    Message,
    Period,
    Quality,
    TrainingType,
)


@dataclass(frozen=True, slots=True)
class BlockMeta:
    type: str
    id: str | None
    title: str


@dataclass(frozen=True, slots=True)
class KpiTileResult:
    meta: BlockMeta
    source: str
    value: float | None
    unit: str
    decimals: int
    delta: float | None = None
    zone: BandZone | None = None
    quality: Quality | None = None
    #: The line under the figure, as a key the interface translates (R78).
    note: Message | None = None


@dataclass(frozen=True, slots=True)
class BandDistributionRow:
    macro: str
    stat: BandStat
    band: Band | None  # band of the last day in the period (display only)
    days_rated: int


@dataclass(frozen=True, slots=True)
class BandDistributionResult:
    meta: BlockMeta
    rows: list[BandDistributionRow]


@dataclass(frozen=True, slots=True)
class ThresholdMark:
    """One class of a scale, in the unit the block shows it in.

    A BMI class is also a weight, and a reader can act on the weight rather than on the
    index. Both live here so nothing has to pair two lists by position and hope they stay
    in step (R81).
    """

    name: str
    lower: float | None
    upper: float | None
    tone: str
    #: The same boundaries in the unit the reader weighs themselves in, when there is one.
    lower_kg: float | None = None
    upper_kg: float | None = None
    #: Kilograms from the current weight to reaching this class; None when already in it.
    to_reach_kg: float | None = None


@dataclass(frozen=True, slots=True)
class RatedValue:
    """A measured value with the class it falls in and the scale behind it."""

    value: float
    unit: str
    band: str
    tone: str
    to_next: float | None
    bands: list[ThresholdMark]


@dataclass(frozen=True, slots=True)
class BodyCompositionResult:
    meta: BlockMeta
    weight_kg: float | None = None
    height_cm: float | None = None
    bmi: RatedValue | None = None
    #: The BMI classes expressed as weights, so a class becomes a number to aim at.
    bmi_weight_bands: list[ThresholdMark] = field(default_factory=list)
    waist_to_height: RatedValue | None = None
    waist_to_hip: RatedValue | None = None
    measured_at: date | None = None
    circumferences: dict[str, float] = field(default_factory=dict)
    #: Change against the previous session, per circumference, in centimetres.
    changes: dict[str, float] = field(default_factory=dict)
    body_fat_pct: float | None = None
    #: Why a figure is absent, one entry per missing input.
    missing: list[Message] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class EnergySplitResult:
    meta: BlockMeta
    tdee_kcal: float | None = None
    basal_kcal: float | None = None
    activity_kcal: float | None = None
    pal: float | None = None
    age_years: int | None = None
    #: Where the expenditure comes from, in words rather than as ``rolling_14d``.
    basis: Message = field(default_factory=lambda: Message("no basis yet"))
    #: Set when the split is physiologically implausible; shown beside the numbers.
    caveat: Message | None = None
    missing: list[Message] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TdeeWindowsResult:
    meta: BlockMeta
    rows: list[RollingRow]
    show_quality: bool
    reference_tdee: int | None
    reference_basis: Message


@dataclass(frozen=True, slots=True)
class TrendResult:
    meta: BlockMeta
    rows: list[TrendRow]


@dataclass(frozen=True, slots=True)
class ForecastResult:
    meta: BlockMeta
    rows: list[ForecastRow]
    horizons: list[str]
    with_eta: bool
    current_kg: float | None
    goal_kg: float
    goal_date: date


@dataclass(frozen=True, slots=True)
class BurndownBlockResult:
    meta: BlockMeta
    result: BurndownResult
    goal_kg: float
    goal_date: date


@dataclass(frozen=True, slots=True)
class WeeklyChartResult:
    meta: BlockMeta
    rows: list[WeekRow]
    series: list[str]


@dataclass(frozen=True, slots=True)
class DayListRow:
    date: date
    macros: Macros
    weight: float | None
    training_type: TrainingType | None
    status: DayStatus | None
    reliable: bool | None
    countable: bool


@dataclass(frozen=True, slots=True)
class TimelineRow:
    date: date
    weight: float | None = None
    weight_ma: float | None = None
    countable: bool = False
    tdee: int | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None


@dataclass(frozen=True, slots=True)
class TimelineResult:
    meta: BlockMeta
    rows: list[TimelineRow]
    tdee_window: int
    goal_kg: float | None = None
    kcal_min: float | None = None
    kcal_max: float | None = None


@dataclass(frozen=True, slots=True)
class DayListResult:
    meta: BlockMeta
    columns: list[str]
    rows: list[DayListRow]


@dataclass(frozen=True, slots=True)
class TextFindingResult:
    meta: BlockMeta
    source: str
    markdown: str | None


@dataclass(frozen=True, slots=True)
class BlockError:
    """A block that could not be computed; the report still renders."""

    meta: BlockMeta
    message: str


BlockResult = (
    KpiTileResult
    | BodyCompositionResult
    | EnergySplitResult
    | BandDistributionResult
    | TdeeWindowsResult
    | TrendResult
    | ForecastResult
    | BurndownBlockResult
    | WeeklyChartResult
    | TimelineResult
    | DayListResult
    | TextFindingResult
    | BlockError
)


@dataclass(frozen=True, slots=True)
class ReportResult:
    name: str
    title: str
    description: str | None
    period: Period
    today: date
    generated_at: datetime
    blocks: list[BlockResult] = field(default_factory=list)

    @property
    def errors(self) -> list[BlockError]:
        return [b for b in self.blocks if isinstance(b, BlockError)]
