"""Report definitions: the YAML document that says which blocks a report has.

Validated with Pydantic (discriminated union over ``type``); the JSON Schema in
``schemas/report-definition.schema.json`` describes the same shape for editors
and CI. See ``docs/REPORTS.md``.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from victus.domain.values import Period

MacroName = Literal["kcal", "protein", "carbs", "fat", "fiber", "salt"]
DayListColumn = Literal[
    "kcal", "protein", "carbs", "fat", "fiber", "salt", "weight", "training", "status", "reliable"
]
WeeklySeries = Literal["kcal", "weight", "tdee"]

_PERIOD_TOKEN = re.compile(r"^(\d+)d$")
_BLOCK_ID = re.compile(r"^[a-z0-9_]+$")
_NAME = re.compile(r"^[a-z0-9-]+$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PeriodSpec(_Strict):
    default: str = "14d"
    options: list[str] = Field(default_factory=lambda: ["7d", "14d", "30d", "90d", "custom"])

    @field_validator("default", "options")
    @classmethod
    def _tokens(cls, v: str | list[str]) -> str | list[str]:
        for token in [v] if isinstance(v, str) else v:
            if token != "custom" and not _PERIOD_TOKEN.match(token):
                raise ValueError(f"invalid period token {token!r} (expected <n>d or custom)")
        return v


class _BlockBase(_Strict):
    id: str | None = None
    title: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str | None) -> str | None:
        if v is not None and not _BLOCK_ID.match(v):
            raise ValueError("block id must match ^[a-z0-9_]+$")
        return v


class KpiTileDef(_BlockBase):
    type: Literal["kpi_tile"]
    id: str
    source: str
    unit: str | None = None
    decimals: int | None = Field(default=None, ge=0, le=3)
    delta_to: str | None = None

    @field_validator("source", "delta_to")
    @classmethod
    def _path(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^[a-z_]+\.[a-z0-9_]+$", v):
            raise ValueError(f"invalid metric path {v!r}")
        return v


class BandDistributionDef(_BlockBase):
    type: Literal["band_distribution"]
    macros: list[MacroName] = Field(min_length=1)


class TdeeWindowsDef(_BlockBase):
    type: Literal["tdee_windows"]
    windows: list[int] | None = None
    show_quality: bool = True


class TrendDef(_BlockBase):
    type: Literal["trend"]
    windows: list[int] | None = None


class ForecastDef(_BlockBase):
    type: Literal["forecast"]
    horizons: list[str] = Field(default_factory=lambda: ["1m", "3m", "6m"])
    with_eta: bool = True

    @field_validator("horizons")
    @classmethod
    def _horizons(cls, v: list[str]) -> list[str]:
        for h in v:
            if not re.match(r"^\d+m$", h):
                raise ValueError(f"invalid horizon {h!r} (expected <n>m)")
        return v


class BurndownDef(_BlockBase):
    type: Literal["burndown"]
    start: date | Literal["from_settings"] | None = None
    stages: Literal["from_settings"] | list[str] = "from_settings"


def _default_series() -> list[WeeklySeries]:
    return ["kcal", "tdee"]


def _default_columns() -> list[DayListColumn]:
    return ["kcal", "protein", "fiber", "weight", "status"]


class WeeklyChartDef(_BlockBase):
    type: Literal["weekly_chart"]
    weeks: int = Field(default=12, ge=1)
    series: list[WeeklySeries] = Field(default_factory=_default_series)


class DayListDef(_BlockBase):
    type: Literal["day_list"]
    columns: list[DayListColumn] = Field(default_factory=_default_columns)
    limit: int = Field(default=14, ge=1)


class TextFindingDef(_BlockBase):
    type: Literal["text_finding"]
    id: str
    source: Literal["agent", "manual", "agent|manual"] = "agent|manual"
    max_items: int = Field(default=5, ge=1, le=10)


BlockDef = Annotated[
    KpiTileDef
    | BandDistributionDef
    | TdeeWindowsDef
    | TrendDef
    | ForecastDef
    | BurndownDef
    | WeeklyChartDef
    | DayListDef
    | TextFindingDef,
    Field(discriminator="type"),
]


class ReportDefinition(_Strict):
    name: str
    title: str
    description: str | None = None
    period: PeriodSpec = Field(default_factory=PeriodSpec)
    blocks: list[BlockDef] = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("report name must match ^[a-z0-9-]+$")
        return v

    def default_period(self, today: date) -> Period:
        return parse_period_token(self.period.default, today)


def load_definition(text: str) -> ReportDefinition:
    """Parse a YAML (or JSON) report definition."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("report definition must be a mapping")
    return ReportDefinition.model_validate(data)


def parse_period_token(token: str, today: date) -> Period:
    """``"14d"`` → the 14 days ending today (inclusive). ``custom`` needs explicit dates."""
    m = _PERIOD_TOKEN.match(token)
    if not m:
        raise ValueError(f"period token {token!r} has no fixed length; pass explicit dates")
    days = int(m.group(1))
    if days < 1:
        raise ValueError("period must cover at least one day")
    return Period(start=today - timedelta(days=days - 1), end=today)
