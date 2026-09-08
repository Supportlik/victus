"""Input records for the day consistency check (``domain/services/validation.py``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from victus.domain.values import DayStatus, Macros


@dataclass(frozen=True, slots=True)
class Tolerances:
    """Absolute/relative tolerances; defaults are the predecessor's values."""

    kcal_abs: float = 3.0
    kcal_rel: float = 0.03
    macro_abs: float = 0.6
    salt_abs: float = 0.06

    def for_macro(self, key: str) -> float:
        if key == "kcal":
            return self.kcal_abs
        if key == "salt":
            return self.salt_abs
        return self.macro_abs


@dataclass(frozen=True, slots=True)
class DayForCheck:
    """Everything the consistency check needs about one day.

    ``source`` are the macros as declared by the source (frontmatter / stored
    totals), ``balance`` the balance table of the source document, ``meal_totals``
    one entry per meal table (``None`` when the table has no total row) and
    ``item_sum`` the sum computed from the individual items.
    """

    day: date
    reliable: bool | None
    status: DayStatus | None
    source: Macros | None = None
    balance: Macros | None = None
    meal_totals: list[Macros | None] = field(default_factory=list)
    item_sum: Macros | None = None
    salt_tracking_start: date | None = None
