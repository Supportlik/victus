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
from victus.domain.values import Band, BandZone, DayStatus, Macros, Period, Quality, TrainingType


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
    note: str | None = None


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
class TdeeWindowsResult:
    meta: BlockMeta
    rows: list[RollingRow]
    show_quality: bool
    reference_tdee: int | None
    reference_basis: str


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
    | BandDistributionResult
    | TdeeWindowsResult
    | TrendResult
    | ForecastResult
    | BurndownBlockResult
    | WeeklyChartResult
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
