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


class MessageOut(Out):
    """A sentence for a person: the English key and the values that belong in it.

    The server does not write the sentence out any more, because a formatted sentence
    cannot be translated. The key is readable English, so a client without a dictionary
    can substitute the parameters itself and be correct (R78).
    """

    key: str
    params: dict[str, str | int | float] = Field(default_factory=dict)


class AttachmentRefOut(Out):
    """One file of a capture; a capture can have several (R65)."""

    id: str
    mime: str
    size: int
    original_name: str | None = None


class TranscriptOut(Out):
    """What one recording of a capture says, and how long it is (R65)."""

    #: The recording this text came from; null only for a transcript stored before a
    #: transcript knew which recording it came from.
    attachment_id: str | None = None
    #: Empty when the provider heard nothing intelligible.
    text: str
    #: Seconds, as the transcription provider measured them.
    duration_s: float | None = None


class FindingOut(Out):
    kind: int
    code: str
    message: MessageOut


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


class RuleOut(Out):
    name: str
    when: str
    then: str
    scope: str
    enabled: bool
    priority: int


class ProductUsageEntryOut(Out):
    date: date
    day_status: str
    meal: str
    line_item_id: int
    amount: float | None = None
    unit_code: str | None = None
    base_amount: float
    base_unit: str
    is_draft: bool
    estimated: bool
    kcal: float | None = None
    protein: float | None = None


class ProductUsageOut(Out):
    product_id: int
    entries: list[ProductUsageEntryOut]
    days: int
    total_base_amount: float
    total_kcal: float
    first_date: date | None = None
    last_date: date | None = None
    #: Line items pointing here in total, so a caller that asked for a window of entries
    #: still learns how much depends on these values.
    item_count: int = 0


class ProductOut(MacrosOut):
    id: int
    name: str
    icon: str | None = None
    brand: str | None = None
    category_id: int | None = None
    category: str | None = None
    reference_amount: float
    reference_unit: Literal["g", "ml"]
    source: str | None = None
    verified: bool
    ean: str | None = None
    note: str | None = None
    #: When these values applied; `valid_until` null means the product is current (R70).
    valid_from: date | None = None
    valid_until: date | None = None
    supersedes_id: int | None = None
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
    #: The portion the amount was resolved through; the unit alone cannot say which (R75).
    portion_id: int | None = None
    portion_label: str | None = None
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
    icon: str | None = None


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
    #: The agent's short verdict on the day; the newest `summary` message of its thread.
    verdict: str | None = None


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
    #: Every file of the capture; `attachment_id` is only the first one (R65).
    attachments: list[AttachmentRefOut] = Field(default_factory=list)
    transcript: str | None = None
    #: One entry per recording, so a length can be shown without playing the audio.
    transcripts: list[TranscriptOut] = Field(default_factory=list)


class WeightEntryOut(Out):
    id: int
    measured_at: datetime
    kg: float
    source: str


class BodyMeasurementOut(Out):
    """One tape-measure session; the values a person did not measure stay null (R76)."""

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


def macros_dict(m: Macros | None) -> dict[str, float | None]:
    return m.as_dict() if m is not None else {}
