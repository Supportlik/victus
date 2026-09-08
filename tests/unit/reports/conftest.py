"""Report-engine fixtures: an in-memory data source fed from the synthetic reference."""

from __future__ import annotations

import json
from datetime import date

import pytest

from tests.unit.domain.conftest import FIXTURE, Reference
from victus.application.ports.report_data import DayMacros, TenantReportSettings
from victus.domain.model.reporting import Stage
from victus.domain.values import (
    Band,
    CalorieCorridor,
    DayStatus,
    Macros,
    TargetBand,
    TrainingType,
)
from victus.reports.memory_source import InMemoryReportDataSource

pytestmark = pytest.mark.reports


@pytest.fixture(scope="session")
def ref() -> Reference:
    """The synthetic reference, re-exposed here (conftests do not share fixtures across dirs)."""
    return Reference(json.loads(FIXTURE.read_text(encoding="utf-8")))


def protein_band(ref: Reference) -> Band:
    pb = ref.protein_band
    return Band(
        min=pb["min"], opt_min=pb["opt"][0], opt_max=pb["opt"][1], target=165, max=pb["max"]
    )


def band_profile(ref: Reference, training_type: TrainingType | None = None) -> TargetBand:
    pb = protein_band(ref)
    generic = Band(min=1, opt_min=2, opt_max=1000, target=10, max=2000)
    return TargetBand(
        name="test",
        training_type=training_type,
        valid_from=date(2020, 1, 1),
        valid_until=None,
        protein=pb,
        carbs=generic,
        fat=generic,
        fiber=Band(min=25, opt_min=32, opt_max=38, target=35, max=50, stretch=38),
        salt=Band(min=4, opt_min=6, opt_max=8, target=7, max=15),
    )


def settings_for(ref: Reference) -> TenantReportSettings:
    return TenantReportSettings(
        goal_kg=ref.goal_kg,
        goal_date=ref.goal_date,
        kcal_per_kg=ref.kcal_per_kg,
        moving_average_days=ref.ma_days,
        trend_windows=tuple(ref.trend_windows),
        tdee_windows=tuple(ref.windows),
        corridor=CalorieCorridor(ref.corridor[0], ref.corridor[1]),
        stages=[Stage(name=n, date=d) for n, d in ref.stages],
        burndown_start=ref.burndown_start,
    )


def days_from_reference(ref: Reference) -> dict[date, DayMacros]:
    """Every logged day of the reference becomes a countable, closed day."""
    days: dict[date, DayMacros] = {}
    for d, kcal in ref.calories.items():
        protein = ref.protein.get(d)
        days[d] = DayMacros(
            date=d,
            macros=Macros(kcal=kcal, protein=protein, fiber=30.0 if protein else None, salt=7.0),
            status=DayStatus.CLOSED,
            reliable=True,
            training_type=None,
            countable=True,
        )
    return days


@pytest.fixture
def source(ref: Reference) -> InMemoryReportDataSource:
    return InMemoryReportDataSource(
        weights=ref.daily,
        days=days_from_reference(ref),
        settings=settings_for(ref),
        bands=[band_profile(ref)],
        findings={"agent": "- first\n- second\n- third"},
    )
