"""Result records of the reporting domain services (TDEE, trend, forecast, burndown).

Plain dataclasses so the report engine, the API and the tests share one shape.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from datetime import date

from victus.domain.values import BandZone, Quality


@dataclass(frozen=True, slots=True)
class BandStat:
    """Distribution of daily values over a target band (see ``band_rating``)."""

    below_min: int
    below_optimum: int
    optimal: int
    above_optimum: int
    above_max: int
    mean: float | None
    n: int

    def zone_counts(self) -> dict[BandZone, int]:
        return {
            BandZone.BELOW_MIN: self.below_min,
            BandZone.BELOW_OPTIMUM: self.below_optimum,
            BandZone.OPTIMAL: self.optimal,
            BandZone.ABOVE_OPTIMUM: self.above_optimum,
            BandZone.ABOVE_MAX: self.above_max,
        }


@dataclass(frozen=True, slots=True)
class TrendRow:
    window: int
    slope_per_day: float | None
    kg_per_week: float | None
    actual_delta: float | None
    start: date
    end: date
    points: int
    measured_days: int


@dataclass(frozen=True, slots=True)
class YearRow:
    year: int
    start: float
    start_date: date
    end: float
    end_date: date
    delta: float | None
    min: float
    max: float
    mean: float
    measured_days: int


@dataclass(frozen=True, slots=True)
class WeekRow:
    """One ISO week (Monday-based bucket) of the predecessor's weekly TDEE table."""

    week_start: date
    mean_kg: float | None
    delta_kg: float | None
    mean_kcal: float | None
    days_with_kcal: int
    tdee: int | None


@dataclass(frozen=True, slots=True)
class RollingRow:
    """Rolling-window TDEE with its quality grade."""

    window_days: int
    start: date
    end: date
    mean_kcal: int | None
    delta_ma_kg: float | None
    tdee: int | None
    rejected_tdee: int | None
    coverage_pct: int
    days_with_kcal: int
    measured_days: int
    days_without_macros: int
    in_corridor: int
    above_corridor: int
    below_corridor: int
    mean_protein: int | None
    quality: Quality | None


@dataclass(frozen=True, slots=True)
class RequiredRate:
    kg_per_week: float
    deficit_kcal_per_day: float
    days_left: int
    to_go_kg: float


@dataclass(frozen=True, slots=True)
class ForecastRow:
    window: int
    kg_per_week: float | None
    m1: float | None
    m3: float | None
    m6: float | None
    at_goal_date: float | None
    eta: date | None


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    date: date


@dataclass(frozen=True, slots=True)
class StageRow:
    name: str
    date: date
    planned_remaining_today: float
    gap: float
    required_kg_per_week: float
    required_pct_per_week: float
    eat_kcal_per_day: float | None
    feasible: bool
    #: the stage's own planned line (anchor → zero on the stage date), for the chart
    path: list[tuple[dt.date, float]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StageOffset:
    """How far a projected crossing lands from one stage date."""

    name: str
    date: dt.date
    #: crossing minus stage date in days: positive is late, negative is early
    days: int


@dataclass(frozen=True, slots=True)
class ProjectionRow:
    """Today's remaining amount carried forward at one trend window's pace.

    ``crossing`` is the day the line reaches zero, the same day the forecast block
    names as its ETA for that window; ``None`` means "not at this pace" (the slope
    is flat, rising or unknown) and then there is no ``path`` either.
    """

    window: int
    slope_per_day: float | None
    kg_per_week: float | None
    crossing: dt.date | None
    #: crossing minus goal date in days: positive is late, negative is early
    days_vs_goal: int | None
    stages: list[StageOffset] = field(default_factory=list)
    #: the dashed line for the chart: [today, remaining] to zero or to the horizon
    path: list[tuple[dt.date, float]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BurndownResult:
    anchor: date
    remaining_at_anchor: float
    remaining_today: float
    planned_remaining_today: float
    gap: float
    burned: float
    days_elapsed: int
    actual_rate_per_week: float
    planned_rate_per_week: float
    required_rate_per_week: float
    target_path: list[tuple[date, float]] = field(default_factory=list)
    actual: list[tuple[date, float]] = field(default_factory=list)
    stages: list[StageRow] = field(default_factory=list)
    #: one row per projection window (R85); empty when projections are switched off
    projections: list[ProjectionRow] = field(default_factory=list)
