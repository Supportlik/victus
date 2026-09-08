"""Value objects and enumerations shared by every layer.

Pure Python: no framework imports (see ``tests/unit/domain/test_purity.py``).
Names are English; ``docs/GLOSSARY.md`` maps them to the German source vault.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from typing import Self

# ── Enumerations ────────────────────────────────────────────────────────────


class ConsumableKind(enum.StrEnum):
    PRODUCT = "product"
    RECIPE_BATCH = "recipe_batch"
    AD_HOC = "ad_hoc"


class UnitType(enum.StrEnum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


class BaseUnit(enum.StrEnum):
    G = "g"
    ML = "ml"


class TrainingType(enum.StrEnum):
    REST = "rest"
    STRENGTH = "strength"
    MARTIAL_ARTS = "martial_arts"


class DayStatus(enum.StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class ItemOrigin(enum.StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    AGENT = "agent"


class SourceKind(enum.StrEnum):
    TRANSCRIPT = "transcript"
    IMAGE = "image"
    TEXT = "text"


class CaptureKind(enum.StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"


class CaptureStatus(enum.StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    ASSIGNED = "assigned"
    PROCESSED = "processed"
    DISCARDED = "discarded"
    FAILED = "failed"


class WeightSource(enum.StrEnum):
    SCALE_SYNC = "scale_sync"
    MANUAL = "manual"
    IMPORT = "import"


class AgentRunner(enum.StrEnum):
    WORKER = "worker"
    EXTERNAL = "external"


class AgentMode(enum.StrEnum):
    HISTORICAL = "historical"
    BATCH = "batch"
    MANUAL = "manual"
    FOLLOW_UP = "follow_up"


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    BUDGET_EXCEEDED = "budget_exceeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(enum.StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class MessageKind(enum.StrEnum):
    TEXT = "text"
    SUMMARY = "summary"
    QUESTION = "question"
    CORRECTION = "correction"
    NOTE = "note"


class Quality(enum.StrEnum):
    """Reliability grade of a rolling TDEE window."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


class BandZone(enum.StrEnum):
    """Where a value sits relative to a target band."""

    BELOW_MIN = "below_min"
    BELOW_OPTIMUM = "below_optimum"
    OPTIMAL = "optimal"
    ABOVE_OPTIMUM = "above_optimum"
    ABOVE_MAX = "above_max"


MACRO_KEYS: tuple[str, ...] = ("kcal", "protein", "carbs", "fat", "fiber", "salt")


# ── Value objects ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Macros:
    """Nutrient amounts. ``None`` means "not declared", never zero."""

    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None

    def scaled(self, factor: float) -> Macros:
        return Macros(**{k: (None if v is None else v * factor) for k, v in self.as_dict().items()})

    def __add__(self, other: Macros) -> Macros:
        def add(a: float | None, b: float | None) -> float | None:
            if a is None and b is None:
                return None
            return (a or 0.0) + (b or 0.0)

        return Macros(**{k: add(getattr(self, k), getattr(other, k)) for k in MACRO_KEYS})

    def as_dict(self) -> dict[str, float | None]:
        return {k: getattr(self, k) for k in MACRO_KEYS}

    @classmethod
    def zero(cls) -> Self:
        return cls(kcal=0.0, protein=0.0, carbs=0.0, fat=0.0, fiber=0.0, salt=0.0)

    def rounded(self) -> Macros:
        """Display rounding used by day totals: kcal integer, salt 2 dp, rest 1 dp."""
        return Macros(
            kcal=None if self.kcal is None else float(round(self.kcal)),
            protein=None if self.protein is None else round(self.protein, 1),
            carbs=None if self.carbs is None else round(self.carbs, 1),
            fat=None if self.fat is None else round(self.fat, 1),
            fiber=None if self.fiber is None else round(self.fiber, 1),
            salt=None if self.salt is None else round(self.salt, 2),
        )


@dataclass(frozen=True, slots=True)
class Band:
    """A target band for one macro: min / optimum range / target / max / optional stretch."""

    min: float
    opt_min: float
    opt_max: float
    target: float
    max: float
    stretch: float | None = None

    def zone(self, value: float) -> BandZone:
        if value < self.min:
            return BandZone.BELOW_MIN
        if value < self.opt_min:
            return BandZone.BELOW_OPTIMUM
        if value <= self.opt_max:
            return BandZone.OPTIMAL
        if value <= self.max:
            return BandZone.ABOVE_OPTIMUM
        return BandZone.ABOVE_MAX


@dataclass(frozen=True, slots=True)
class TargetBand:
    """One complete band profile (all macros) for a training type and validity period."""

    name: str
    training_type: TrainingType | None
    valid_from: date
    valid_until: date | None
    protein: Band
    carbs: Band
    fat: Band
    fiber: Band
    salt: Band
    kcal: Band | None = None

    def band_for(self, macro: str) -> Band | None:
        return getattr(self, macro, None)


@dataclass(frozen=True, slots=True)
class CalorieCorridor:
    min: int
    max: int
    asymmetric: bool = True


@dataclass(frozen=True, slots=True)
class Quantity:
    """A quantity as captured: number + unit code, plus optional free text."""

    amount: float | None
    unit_code: str | None
    raw: str = ""
    estimated: bool = False
    portion_label: str | None = None  # e.g. "tub", "slice" when a count unit was used


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """A product/recipe candidate proposed by the matcher."""

    consumable_id: int
    name: str
    kind: ConsumableKind
    tier: int  # 1 exact, 2 exact without parentheses, 3 fuzzy
    score: float


@dataclass(frozen=True, slots=True)
class Finding:
    """Result of a consistency check on a day (see ``domain/services/validation.py``)."""

    kind: int  # 0 flags missing, 1 frontmatter/table drift, 2 table/items mismatch, 3 gaps
    code: str
    message: str
    day: date | None = None
    details: dict[str, float | str] = field(default_factory=dict)
