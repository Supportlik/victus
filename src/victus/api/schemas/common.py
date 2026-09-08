"""Shared response building blocks."""

from __future__ import annotations

import datetime as dt
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from victus.domain.values import Macros


class Out(BaseModel):
    """Response base: built from dataclasses / ORM rows."""

    model_config = ConfigDict(from_attributes=True)


class MacrosOut(Out):
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None

    @classmethod
    def from_macros(cls, m: Macros | None) -> MacrosOut:
        if m is None:
            return cls()
        return cls(**m.as_dict())


class BandSpecOut(Out):
    min: float
    opt_min: float
    opt_max: float
    target: float
    max: float
    stretch: float | None = None


class TargetBandOut(Out):
    id: int
    name: str
    training_type: str | None
    valid_from: date
    valid_until: date | None
    kcal: BandSpecOut | None
    protein: BandSpecOut
    carbs: BandSpecOut
    fat: BandSpecOut
    fiber: BandSpecOut
    salt: BandSpecOut
    note: str | None


class FindingOut(Out):
    kind: int
    code: str
    message: str


class UnitOut(Out):
    code: str
    singular: str
    plural: str
    unit_type: str


class CategoryOut(Out):
    id: int
    name: str


class PortionOut(Out):
    id: int
    product_id: int
    unit_code: str
    label: str
    description: str | None = None
    amount: float
    amount_unit: Literal["g", "ml"]
    is_default: bool
    weight_source: str | None = None


class ProductOut(MacrosOut):
    id: int
    name: str
    brand: str | None = None
    category_id: int | None = None
    category: str | None = None
    reference_amount: float
    reference_unit: Literal["g", "ml"]
    source: str | None = None
    verified: bool
    ean: str | None = None
    note: str | None = None
    portions: list[PortionOut] = Field(default_factory=list)


class MatchCandidateOut(Out):
    consumable_id: int
    name: str
    kind: str
    tier: int
    score: float


class LineItemOut(MacrosOut):
    id: int
    meal_id: int
    position: int
    consumable_id: int
    consumable_name: str
    consumable_kind: str
    amount: float | None
    unit_code: str | None
    base_amount: float
    base_unit: str
    estimated: bool
    amount_estimated: bool
    is_draft: bool
    confidence: float | None = None
    rationale: str | None = None
    alternatives: list[dict[str, Any]] | None = None
    raw_text: str | None = None
    source_capture_id: str | None = None
    source_kind: str | None = None
    category: str | None = None


class MealOut(Out):
    id: int
    position: int
    name: str
    time: dt.time | None = None
    line_items: list[LineItemOut]
    totals: MacrosOut

    @field_serializer("time")
    def _ser_time(self, v: dt.time | None) -> str | None:
        return v.isoformat(timespec="minutes") if v else None


class DaySummaryOut(Out):
    date: date
    status: str
    reliable: bool | None
    training_type: str | None
    macros: MacrosOut
    has_drafts: bool = False
    weight_kg: float | None = None


class DayOut(DaySummaryOut):
    weekday: str | None = None
    meals: list[MealOut]
    target_band: TargetBandOut | None
    zones: dict[str, str] = Field(default_factory=dict)
    findings: list[FindingOut] = Field(default_factory=list)
    notes: str | None = None


class DayMessageOut(Out):
    id: str
    role: str
    kind: str
    content: str
    created_at: datetime
    processing_state: str | None = None
    capture_id: str | None = None
    capture_kind: str | None = None
    attachment_id: str | None = None
    attachment_mime: str | None = None
    transcript: str | None = None


class WeightEntryOut(Out):
    id: int
    measured_at: datetime
    kg: float
    source: str


def macros_dict(m: Macros | None) -> dict[str, float | None]:
    return m.as_dict() if m is not None else {}
