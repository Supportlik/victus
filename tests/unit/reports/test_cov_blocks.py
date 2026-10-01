"""T-RPT-200…213: report engine edges — definitions, registry, context, metrics and blocks."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from victus.application.ports.report_data import (
    BodyProfile,
    BodySession,
    DayMacros,
    TenantReportSettings,
)
from victus.domain.values import CalorieCorridor, DayStatus, Macros, Period
from victus.reports import metrics
from victus.reports.blocks import COMPUTERS
from victus.reports.blocks.body import _bmi_marks
from victus.reports.context import ReportContext
from victus.reports.definition import (
    BandDistributionDef,
    BodyCompositionDef,
    BurndownDef,
    EnergySplitDef,
    KpiTileDef,
    TimelineDef,
    TrendDef,
    WeeklyChartDef,
    load_definition,
)
from victus.reports.memory_source import InMemoryReportDataSource
from victus.reports.messages import basis_message, tdee_from
from victus.reports.registry import ReportRegistry
from victus.reports.render.json import to_dict
from victus.reports.results import (
    BandDistributionResult,
    BlockMeta,
    BodyCompositionResult,
    BurndownBlockResult,
    EnergySplitResult,
    KpiTileResult,
    ReportResult,
    WeeklyChartResult,
)

from .conftest import band_profile, days_from_reference, settings_for

pytestmark = pytest.mark.reports

D0 = date(2026, 3, 2)  # a Monday
D0_DT = datetime(2026, 3, 2, 12, 0)
SETTINGS = TenantReportSettings(goal_kg=70.0, goal_date=date(2026, 12, 31))


def _synthetic(
    n_days: int = 28,
    *,
    kcal: float = 1800.0,
    settings: TenantReportSettings = SETTINGS,
    weights: bool = True,
) -> InMemoryReportDataSource:
    """Four weeks of illustrative data: a slow, steady loss at a constant intake."""
    days = {
        D0 + timedelta(days=i): DayMacros(
            date=D0 + timedelta(days=i),
            macros=Macros(kcal=kcal, protein=120.0),
            status=DayStatus.CLOSED,
            reliable=True,
            countable=True,
        )
        for i in range(n_days)
    }
    w = {D0 + timedelta(days=i): 85.0 - 0.05 * i for i in range(n_days)} if weights else {}
    return InMemoryReportDataSource(weights=w, days=days, settings=settings)


def _ctx(source: InMemoryReportDataSource, start: date, end: date, today: date) -> ReportContext:
    return ReportContext(source, Period(start, end), today)


def _last() -> date:
    return D0 + timedelta(days=27)


def test_basis_messages_name_every_basis() -> None:
    """T-RPT-200: rolling, weekly, none and an unknown basis each read as a sentence."""
    assert basis_message("rolling_14d").params == {"n": 14}
    assert basis_message("weekly_mean_8w").fill() == "mean of the last 8 weekly values"
    assert basis_message("none").fill() == "no basis yet"
    assert basis_message("manual").fill() == "manual"
    assert tdee_from("rolling_7d").fill() == "TDEE from the rolling 7-day window"
    assert tdee_from("weekly_mean_8w").fill() == "TDEE from the mean of 8 weekly values"
    assert tdee_from("none").fill() == "TDEE, no basis yet"


TENANT_YAML = "name: mine\ntitle: Mine\nblocks:\n  - type: weekly_chart\n"


def test_registry_adds_tenant_reports_without_shadowing() -> None:
    """T-RPT-201: a tenant report is listed and found; a built-in name is not overridden."""
    builtin = ReportRegistry().list()[0]
    shadow = load_definition(f"name: {builtin.name}\ntitle: Shadow\nblocks:\n  - type: trend\n")
    mine = load_definition(TENANT_YAML)
    registry = ReportRegistry(tenant_loader=lambda: [shadow, mine])
    names = [d.name for d in registry.list()]
    assert names.count(builtin.name) == 1 and "mine" in names
    assert registry.get(builtin.name).title == builtin.title
    assert registry.get("mine") is mine
    assert registry.is_builtin(builtin.name) and not registry.is_builtin("mine")
    with pytest.raises(KeyError, match="unknown report"):
        registry.get("nope")
    with pytest.raises(KeyError, match="unknown report"):
        ReportRegistry().get("mine")


def test_definition_validation() -> None:
    """T-RPT-202: bad horizons, non-mapping YAML and a zero-day period are refused."""
    with pytest.raises(ValueError, match="invalid horizon"):
        load_definition("name: x\ntitle: X\nblocks:\n  - type: forecast\n    horizons: [2w]\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_definition("- just\n- a list\n")
    zero = load_definition("name: x\ntitle: X\nperiod: {default: 0d}\nblocks: [{type: trend}]\n")
    with pytest.raises(ValueError, match="at least one day"):
        zero.default_period(D0)
    defn = load_definition("name: x\ntitle: X\nperiod: {default: 7d}\nblocks: [{type: trend}]\n")
    assert defn.default_period(D0) == Period(D0 - timedelta(days=6), D0)


def test_json_renders_nan_as_null() -> None:
    """T-RPT-203: a NaN figure becomes JSON null instead of an invalid token."""
    kpi = KpiTileResult(BlockMeta("kpi_tile", "k", "K"), "weight.latest", float("nan"), "kg", 1)
    result = ReportResult("x", "X", None, Period(D0, D0), D0, D0_DT, [kpi])
    data = to_dict(result)
    assert data["blocks"][0]["value"] is None
    assert data["blocks"][0]["error"] is False


def test_memory_source_filters_by_period() -> None:
    """T-RPT-204: the in-memory source returns only what lies inside the period."""
    source = _synthetic()
    week = Period(D0, D0 + timedelta(days=6))
    assert sorted(source.weights(week)) == [D0 + timedelta(days=i) for i in range(7)]
    assert len(source.day_macros(week)) == 7


def test_a_block_computer_rejects_the_wrong_definition() -> None:
    """T-RPT-205: handing a KPI definition to the trend computer is a TypeError."""
    ctx = _ctx(_synthetic(), D0, _last(), _last())
    with pytest.raises(TypeError, match="expected TrendDef, got KpiTileDef"):
        COMPUTERS["trend"](KpiTileDef(type="kpi_tile", id="k", source="weight.latest"), ctx)
    assert TrendDef(type="trend").type == "trend"


def test_a_symmetric_corridor_counts_low_days_below_min() -> None:
    """T-RPT-206: without asymmetry a day under the corridor is below min, not below optimum."""
    settings = replace(SETTINGS, corridor=CalorieCorridor(1400, 2000, asymmetric=False))
    ctx = _ctx(_synthetic(kcal=1200.0, settings=settings), D0, _last(), _last())
    result = COMPUTERS["band_distribution"](
        BandDistributionDef(type="band_distribution", macros=["kcal"]), ctx
    )
    assert isinstance(result, BandDistributionResult)
    stat = result.rows[0].stat
    assert (stat.below_min, stat.below_optimum, stat.n) == (28, 0, 28)


def test_kpi_tile_deltas() -> None:
    """T-RPT-207: delta_to compares two metrics; no previous period value → no delta."""
    ctx = _ctx(_synthetic(), D0 + timedelta(days=21), _last(), _last())
    tile = COMPUTERS["kpi_tile"](
        KpiTileDef(type="kpi_tile", id="k", source="weight.latest", delta_to="weight.ma"), ctx
    )
    assert isinstance(tile, KpiTileResult)
    assert tile.value == pytest.approx(83.65)
    # 83.65 - 83.80 on a falling series, rounded to the metric's one decimal
    assert tile.delta == pytest.approx(-0.1), "latest weigh-in minus the 7-day average"

    first_week = _ctx(_synthetic(), D0, D0 + timedelta(days=6), D0 + timedelta(days=6))
    tile = COMPUTERS["kpi_tile"](
        KpiTileDef(type="kpi_tile", id="k", source="kcal.average"), first_week
    )
    assert isinstance(tile, KpiTileResult)
    assert tile.value == 1800.0
    assert tile.delta is None, "the week before holds no logged days"


def test_weekly_chart_block() -> None:
    """T-RPT-208: the last N weeks, with the chosen series; no data is an error."""
    ctx = _ctx(_synthetic(), D0, _last(), _last())
    result = COMPUTERS["weekly_chart"](
        WeeklyChartDef(type="weekly_chart", weeks=2, series=["kcal", "weight", "tdee"]), ctx
    )
    assert isinstance(result, WeeklyChartResult)
    assert [r.week_start for r in result.rows] == [D0 + timedelta(days=14), D0 + timedelta(days=21)]
    assert result.series == ["kcal", "weight", "tdee"]
    empty = InMemoryReportDataSource(weights={}, days={}, settings=SETTINGS)
    with pytest.raises(ValueError, match="no weekly data"):
        COMPUTERS["weekly_chart"](WeeklyChartDef(type="weekly_chart"), _ctx(empty, D0, D0, D0))


def test_timeline_of_an_empty_period_is_an_error() -> None:
    """T-RPT-209: a period that ends before it starts has no days to show."""
    ctx = _ctx(_synthetic(), D0 + timedelta(days=5), D0, _last())
    with pytest.raises(ValueError, match="empty period"):
        COMPUTERS["timeline"](TimelineDef(type="timeline"), ctx)


def test_burndown_block_start_and_stages(ref: Reference) -> None:
    """T-RPT-210: an explicit start date, the period start as fallback, named stages only,
    and a goal already reached is an error."""
    end = max(ref.daily)
    settings = settings_for(ref)

    def ctx(s: TenantReportSettings) -> ReportContext:
        source = InMemoryReportDataSource(
            weights=ref.daily, days=days_from_reference(ref), settings=s, bands=[band_profile(ref)]
        )
        return ReportContext(source, Period(end - timedelta(days=29), end), end)

    explicit = end - timedelta(days=20)
    first = settings.stages[0].name
    result = COMPUTERS["burndown"](
        BurndownDef(type="burndown", start=explicit, stages=[first]), ctx(settings)
    )
    assert isinstance(result, BurndownBlockResult)
    assert result.result.anchor >= explicit
    assert {s.name for s in result.result.stages} <= {first}

    fallback = COMPUTERS["burndown"](
        BurndownDef(type="burndown"), ctx(replace(settings, burndown_start=None))
    )
    assert isinstance(fallback, BurndownBlockResult)
    assert fallback.result.anchor >= end - timedelta(days=29)

    with pytest.raises(ValueError, match="not computable"):
        COMPUTERS["burndown"](BurndownDef(type="burndown"), ctx(replace(settings, goal_kg=500.0)))


def test_context_edges() -> None:
    """T-RPT-211: the MA of the last weigh-in stands in for a later today; no weights → no
    latest weight; windows beyond the settings are computed on demand."""
    today = _last() + timedelta(days=3)
    ctx = _ctx(_synthetic(), D0, today, today)
    assert ctx.current_kg == ctx.ma[_last()]
    assert ctx.rolling_for(None) == ctx.rolling
    [extra] = ctx.rolling_for([5])
    assert extra.window_days == 5 and 5 not in SETTINGS.tdee_windows

    bare = _ctx(_synthetic(weights=False), D0, _last(), _last())
    assert bare.latest_weight is None
    assert bare.rolling_for([7]) == []


def test_metrics_without_weights() -> None:
    """T-RPT-212: weight change and rolling TDEE are absent, not zero, without weigh-ins."""
    ctx = _ctx(_synthetic(weights=False), D0, _last(), _last())
    delta = metrics.resolve("weight.delta_week", ctx)
    assert delta.value is None and delta.unit == "kg"
    rolling = metrics.resolve("tdee.rolling_7", ctx)
    assert rolling.value is None and rolling.unit == "kcal"


def test_body_blocks_name_the_missing_input() -> None:
    """T-RPT-213: waist to hip without a sex, an energy split without a birth date, and the
    BMI classes without a weight carry no distances."""
    source = replace_source(
        _synthetic(),
        body_profile=BodyProfile(height_cm=175.0),
        body_sessions=[BodySession(measured_at=D0, waist_cm=90.0, hip_cm=100.0)],
    )
    ctx = _ctx(source, D0, _last(), _last())
    body = COMPUTERS["body_composition"](BodyCompositionDef(type="body_composition"), ctx)
    assert isinstance(body, BodyCompositionResult)
    assert body.waist_to_hip is None
    assert any(m.key == "waist to hip needs the sex, which is not set" for m in body.missing)

    energy = COMPUTERS["energy_split"](EnergySplitDef(type="energy_split"), ctx)
    assert isinstance(energy, EnergySplitResult)
    assert energy.tdee_kcal is not None and energy.basal_kcal is None
    assert {m.key for m in energy.missing} >= {
        "birth date is not set in the settings",
        "sex is not set in the settings",
    }

    marks = _bmi_marks(175.0, None)
    assert next(m.name for m in marks) == "underweight"
    assert all(m.to_reach_kg is None for m in marks)


def replace_source(
    source: InMemoryReportDataSource,
    *,
    body_profile: BodyProfile,
    body_sessions: list[BodySession],
) -> InMemoryReportDataSource:
    return InMemoryReportDataSource(
        weights=source.all_weights(),
        days=source.all_day_macros(),
        settings=source.settings(),
        body_profile=body_profile,
        body_sessions=body_sessions,
    )
