"""Read-only data the report engine needs, as a port.

The engine never touches repositories directly; an adapter (SQLAlchemy, in-memory,
vault export) implements :class:`ReportDataSource`. Everything here is plain
Python so the reports package stays framework-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from victus.domain.model.reporting import Stage
from victus.domain.values import (
    CalorieCorridor,
    DayStatus,
    Macros,
    Period,
    TargetBand,
    TrainingType,
)


@dataclass(frozen=True, slots=True)
class DayMacros:
    """Computed totals of one day plus the flags that decide whether it counts."""

    date: date
    macros: Macros
    status: DayStatus | None
    reliable: bool | None
    training_type: TrainingType | None = None
    countable: bool = False


@dataclass(frozen=True, slots=True)
class TenantReportSettings:
    """The subset of tenant settings the report engine reads."""

    goal_kg: float
    goal_date: date
    kcal_per_kg: float = 7716.17
    moving_average_days: int = 7
    trend_windows: Sequence[int] = (7, 14, 21, 30, 60, 90)
    tdee_windows: Sequence[int] = (3, 7, 14, 21, 30, 60, 90)
    corridor: CalorieCorridor = field(default_factory=lambda: CalorieCorridor(1400, 2000))
    stages: Sequence[Stage] = ()
    burndown_start: date | None = None
    #: name of the active goal, when the tenant keeps several
    goal_name: str | None = None


@dataclass(frozen=True, slots=True)
class BodyProfile:
    """What the body figures need, all of it optional (R76).

    None means the tenant has not stated it. A block that needs a missing field says so
    rather than substituting an average, because a BMI computed on a guessed height is
    worse than no BMI.
    """

    height_cm: float | None = None
    sex: str | None = None
    birth_date: date | None = None


@dataclass(frozen=True, slots=True)
class BodySession:
    """One tape-measure session, as the report reads it."""

    measured_at: date
    waist_cm: float | None = None
    belly_cm: float | None = None
    hip_cm: float | None = None
    chest_cm: float | None = None
    neck_cm: float | None = None
    thigh_cm: float | None = None
    arm_cm: float | None = None
    body_fat_pct: float | None = None


class ReportDataSource(Protocol):
    """Everything a report render needs to read, scoped to one tenant."""

    def weights(self, period: Period) -> Mapping[date, float]:
        """Daily mean weight inside ``period``."""
        ...

    def all_weights(self) -> Mapping[date, float]:
        """Daily mean weight for the whole history (moving averages need run-up)."""
        ...

    def day_macros(self, period: Period) -> Mapping[date, DayMacros]:
        """Computed totals for every day log inside ``period`` (all statuses)."""
        ...

    def all_day_macros(self) -> Mapping[date, DayMacros]:
        """Computed totals for the whole history (weekly TDEE needs run-up)."""
        ...

    def target_band_for(self, day: date, training_type: TrainingType | None) -> TargetBand | None:
        """The band profile valid on ``day``."""
        ...

    def settings(self) -> TenantReportSettings: ...

    def body_profile(self) -> BodyProfile:
        """Height, sex and birth date from the tenant settings; any may be missing."""
        ...

    def body_sessions(self, on_or_before: date | None = None) -> Sequence[BodySession]:
        """Tape-measure sessions up to a day, oldest first."""
        ...

    def latest_finding(self, source: str) -> str | None:
        """Markdown of the newest finding for ``source`` (``agent`` or ``manual``)."""
        ...
