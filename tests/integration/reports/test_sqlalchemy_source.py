"""T-RPT-016/017: the SQLAlchemy report data source feeds the engine from real tables."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.integration.db.conftest import add_item, make_day, make_product
from victus.domain.values import Period, TrainingType
from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.reports.sqlalchemy_source import (
    SqlAlchemyReportDataSource,
    band_from_orm,
    settings_from_data,
)
from victus.reports.engine import ReportEngine
from victus.reports.registry import ReportRegistry
from victus.reports.render.json import to_dict
from victus.reports.render.markdown import to_markdown

pytestmark = pytest.mark.service

SETTINGS = {
    "goal": {
        "weight_kg": 85.0,
        "date": "2027-03-31",
        "stages": [{"name": "Target", "date": "2027-03-31"}],
    },
    "kcal_per_kg": 7716.17,
    "moving_average_days": 7,
    "trend_windows": [7, 14],
    "tdee_windows": [7, 14],
    "calorie_corridor": {"min": 1800, "max": 2200, "asymmetric": True},
}


def _band_row(tenant_id: str) -> orm.TargetBand:
    values: dict[str, object] = {
        "tenant_id": tenant_id,
        "name": "Rest",
        "training_type": "rest",
        "valid_from": date(2026, 1, 1),
    }
    for macro, (mn, omn, omx, tgt, mx) in {
        "protein": (105, 150, 185, 165, 200),
        "carbs": (120, 155, 200, 180, 230),
        "fat": (45, 55, 70, 58, 75),
        "fiber": (25, 32, 38, 35, 50),
        "salt": (4, 6, 8, 7, 15),
    }.items():
        values.update(
            {
                f"{macro}_min": mn,
                f"{macro}_opt_min": omn,
                f"{macro}_opt_max": omx,
                f"{macro}_target": tgt,
                f"{macro}_max": mx,
            }
        )
    values["protein_stretch"] = 185
    return orm.TargetBand(**values)  # type: ignore[arg-type]


def _seed(u: SqlAlchemyUnitOfWork, days: int = 21) -> None:
    u.settings.add_version(SETTINGS, valid_from=date(2026, 1, 1), changed_by="test")
    u.target_bands.add(_band_row(u.ctx.tenant_id))
    skyr = make_product(u, "Skyr natural")
    start = date(2026, 3, 1)
    for i in range(days):
        day = start + timedelta(days=i)
        log = make_day(u, day, training_type="rest")
        add_item(u, log, skyr.id, 400 + 10 * i)
        u.weights.add(
            orm.WeightEntry(
                tenant_id=u.ctx.tenant_id,
                measured_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
                kg=90.0 - 0.1 * i,
                source="import",
            )
        )
    u.commit()


def test_source_reads_days_weights_bands_and_settings(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        _seed(uow)
        _assert_source(uow)


def _assert_source(uow: SqlAlchemyUnitOfWork) -> None:
    src = SqlAlchemyReportDataSource(uow)
    period = Period(date(2026, 3, 8), date(2026, 3, 21))

    weights = src.weights(period)
    assert len(weights) == 14
    assert abs(weights[date(2026, 3, 21)] - 88.0) < 1e-6

    days = src.day_macros(period)
    assert len(days) == 14
    d = days[date(2026, 3, 21)]
    assert d.countable is True
    assert d.macros.kcal == pytest.approx((400 + 200) * 63.0 / 100, abs=1)
    assert d.training_type is TrainingType.REST

    band = src.target_band_for(date(2026, 3, 10), TrainingType.REST)
    assert band is not None and band.protein.opt_min == 150

    settings = src.settings()
    assert settings.goal_kg == 85.0 and settings.corridor.max == 2200
    assert src.latest_finding("agent") is None


def test_checkup_renders_from_database(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        _seed(uow)
        _assert_checkup(uow)


def _assert_checkup(uow: SqlAlchemyUnitOfWork) -> None:
    src = SqlAlchemyReportDataSource(uow)
    definition = ReportRegistry().get("checkup")
    result = ReportEngine(src).render(
        definition, Period(date(2026, 3, 8), date(2026, 3, 21)), today=date(2026, 3, 21)
    )
    assert not result.errors, [e.message for e in result.errors]
    payload = to_dict(result)
    assert payload["name"] == "checkup"
    types = [b["meta"]["type"] for b in payload["blocks"]]
    assert "tdee_windows" in types and "band_distribution" in types
    md = to_markdown(result)
    assert "Am I on track?" in md


def test_band_and_settings_conversion_edge_cases() -> None:
    row = _band_row("t")
    band = band_from_orm(row)
    assert band.kcal is None and band.protein.stretch == 185
    s = settings_from_data({})
    assert s.kcal_per_kg == 7716.17 and s.corridor.min == 1400


def test_timeline_block_lines_up_weight_intake_and_tdee(uow: SqlAlchemyUnitOfWork) -> None:
    """T-RPT-010: one row per day of the period, with the rolling TDEE ending on it."""
    from victus.reports.definition import ReportDefinition
    from victus.reports.results import TimelineResult

    definition = ReportDefinition.model_validate(
        {
            "name": "timeline-only",
            "title": "Timeline",
            "period": {"default": "7d", "options": ["7d"]},
            "blocks": [{"type": "timeline", "tdee_window": 7}],
        }
    )
    end = date(2026, 3, 10)
    period = Period(end - timedelta(days=6), end)
    with uow:
        result = ReportEngine(SqlAlchemyReportDataSource(uow)).render(definition, period, today=end)
    block = result.blocks[0]
    assert isinstance(block, TimelineResult)
    assert [r.date for r in block.rows] == [period.start + timedelta(days=i) for i in range(7)]
    assert block.tdee_window == 7
    assert block.kcal_min is not None and block.kcal_max is not None
