"""T-RPT-004 … T-RPT-011, T-RPT-014/015: reference reproduction and graceful degradation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from tests.unit.reports.conftest import band_profile, days_from_reference, settings_for
from victus.application.ports.report_data import DayMacros
from victus.domain.values import DayStatus, Macros, Period, Quality
from victus.reports import metrics
from victus.reports.definition import load_definition
from victus.reports.engine import ReportEngine
from victus.reports.memory_source import InMemoryReportDataSource
from victus.reports.registry import ReportRegistry
from victus.reports.results import (
    BandDistributionResult,
    BlockError,
    BurndownBlockResult,
    DayListResult,
    ForecastResult,
    KpiTileResult,
    TdeeWindowsResult,
    TextFindingResult,
    TrendResult,
)

pytestmark = pytest.mark.reports


def _render(source: InMemoryReportDataSource, ref: Reference, yaml_text: str):  # type: ignore[no-untyped-def]
    engine = ReportEngine(source)
    definition = load_definition(yaml_text)
    period = Period(ref.today - timedelta(days=13), ref.today)
    return engine.render(definition, period, ref.today)


def test_tdee_windows_match_reference(source: InMemoryReportDataSource, ref: Reference) -> None:
    windows = ", ".join(str(w) for w in ref.windows)
    res = _render(
        source,
        ref,
        f"name: t\ntitle: t\nblocks:\n  - {{type: tdee_windows, windows: [{windows}]}}\n",
    )
    block = res.blocks[0]
    assert isinstance(block, TdeeWindowsResult)
    assert [r.window_days for r in block.rows] == ref.windows
    for row in block.rows:
        exp = ref.out["rolling"][str(row.window_days)]
        assert row.mean_kcal == exp["kcal"]
        assert row.delta_ma_kg == exp["delta"]
        assert row.tdee == exp["tdee"]
        assert row.coverage_pct == exp["abdeckung"]
        assert (row.quality.value if row.quality else None) == exp["quality"]
    assert block.reference_tdee == ref.out["rolling"]["14"]["tdee"]
    assert block.reference_basis.params == {"n": 14}


def test_trend_and_forecast_match_reference(
    source: InMemoryReportDataSource, ref: Reference
) -> None:
    res = _render(
        source, ref, "name: t\ntitle: t\nblocks:\n  - {type: trend}\n  - {type: forecast}\n"
    )
    trend, fc = res.blocks
    assert isinstance(trend, TrendResult) and isinstance(fc, ForecastResult)
    for row, exp in zip(trend.rows, ref.out["trends"], strict=True):
        assert row.window == exp["tage"]
        assert row.slope_per_day == pytest.approx(exp["slope"], abs=1e-9)
        assert row.kg_per_week == exp["rate"]
        assert row.actual_delta == exp["diff"]
    for row, exp in zip(fc.rows, ref.out["forecast"], strict=True):
        assert row.window == exp["tage"]
        assert row.m1 == pytest.approx(exp["m1"], abs=0.01)
        assert row.m3 == pytest.approx(exp["m3"], abs=0.01)
        assert row.m6 == pytest.approx(exp["m6"], abs=0.01)
        assert row.at_goal_date == pytest.approx(exp["am_ziel"], abs=0.01)
        assert (row.eta.isoformat() if row.eta else None) == exp["eta"]


def test_burndown_matches_reference(source: InMemoryReportDataSource, ref: Reference) -> None:
    res = _render(source, ref, "name: t\ntitle: t\nblocks:\n  - {type: burndown}\n")
    block = res.blocks[0]
    assert isinstance(block, BurndownBlockResult)
    r, exp = block.result, ref.out["burndown"]
    assert r.anchor.isoformat() == exp["anchor"]
    assert r.remaining_at_anchor == pytest.approx(exp["rest0"], abs=0.01)
    assert r.remaining_today == pytest.approx(exp["ist"], abs=0.01)
    assert r.planned_remaining_today == pytest.approx(exp["soll"], abs=0.01)
    assert r.days_elapsed == exp["tage"]
    assert r.actual_rate_per_week == pytest.approx(exp["rate_ist"], abs=0.001)
    assert r.required_rate_per_week == pytest.approx(exp["rate_noetig"], abs=0.001)
    assert [s.name for s in r.stages] == [s["name"] for s in exp["stufen"]]
    for st, e in zip(r.stages, exp["stufen"], strict=True):
        assert st.required_kg_per_week == pytest.approx(e["rate_noetig"], abs=0.001)
        assert st.required_pct_per_week == pytest.approx(e["pct"], abs=0.001)


def test_band_distribution_sums(ref: Reference) -> None:
    """Whole history as period so the protein distribution equals the reference."""
    source = InMemoryReportDataSource(
        weights=ref.daily,
        days=days_from_reference(ref),
        settings=settings_for(ref),
        bands=[band_profile(ref)],
    )
    definition = load_definition(
        "name: t\ntitle: t\nblocks:\n  - {type: band_distribution, macros: [protein, kcal]}\n"
    )
    period = Period(min(ref.calories), ref.today)
    res = ReportEngine(source).render(definition, period, ref.today)
    block = res.blocks[0]
    assert isinstance(block, BandDistributionResult)
    protein, kcal = block.rows
    exp = ref.out["protein_distribution"]
    s = protein.stat
    assert s.n == exp["n"] == protein.days_rated
    assert s.below_min == exp["below_min"]
    assert s.optimal == exp["optimal"]
    assert s.above_max == exp["above_max"]
    assert s.below_optimum + s.above_optimum == exp["between"]
    assert s.below_min + s.below_optimum + s.optimal + s.above_optimum + s.above_max == s.n
    k = kcal.stat
    assert k.n == len(ref.calories)
    assert k.below_min == 0  # asymmetric corridor: below min is not a finding
    assert k.below_optimum + k.optimal + k.above_max == k.n


def test_every_kpi_path_resolves(source: InMemoryReportDataSource, ref: Reference) -> None:
    tiles = "\n".join(
        f"  - {{type: kpi_tile, id: k{i}, source: {path}}}"
        for i, path in enumerate(metrics.PROVIDERS)
    )
    res = _render(source, ref, f"name: t\ntitle: t\nblocks:\n{tiles}\n")
    assert not res.errors
    by_source = {b.source: b for b in res.blocks if isinstance(b, KpiTileResult)}
    assert by_source["weight.ma7"].value == ref.out["moving_average"][ref.today.isoformat()]
    assert by_source["tdee.rolling_14"].value == ref.out["rolling"]["14"]["tdee"]
    assert by_source["tdee.rolling_14"].quality is Quality.GREEN
    assert by_source["goal.rate_kg_per_week"].value is not None
    assert (
        by_source["kcal.average"].value is not None and by_source["kcal.average"].zone is not None
    )
    assert by_source["protein.average"].zone is not None


def test_unknown_metric_path_is_a_block_error_only(
    source: InMemoryReportDataSource, ref: Reference
) -> None:
    res = _render(
        source,
        ref,
        "name: t\ntitle: t\nblocks:\n"
        "  - {type: kpi_tile, id: k, source: weight.nonsense}\n  - {type: trend}\n",
    )
    assert isinstance(res.blocks[0], BlockError) and "weight.nonsense" in res.blocks[0].message
    assert isinstance(res.blocks[1], TrendResult)
    assert len(res.errors) == 1


def test_day_list_limit_columns_and_countable_flag(ref: Reference) -> None:
    days = days_from_reference(ref)
    last = max(days)
    days[last] = DayMacros(last, days[last].macros, DayStatus.OPEN, True, None, countable=False)
    source = InMemoryReportDataSource(weights=ref.daily, days=days, settings=settings_for(ref))
    res = _render(
        source,
        ref,
        "name: t\ntitle: t\nblocks:\n"
        "  - {type: day_list, limit: 5, columns: [kcal, weight, status]}\n",
    )
    block = res.blocks[0]
    assert isinstance(block, DayListResult)
    assert block.columns == ["kcal", "weight", "status"]
    assert len(block.rows) == 5
    assert block.rows[0].date == last and block.rows[0].countable is False
    assert block.rows[0].weight == ref.daily.get(last)
    assert [r.date for r in block.rows] == sorted((r.date for r in block.rows), reverse=True)


def test_text_finding_empty_and_limited(ref: Reference) -> None:
    empty = InMemoryReportDataSource(
        weights=ref.daily, days=days_from_reference(ref), settings=settings_for(ref)
    )
    res = _render(empty, ref, "name: t\ntitle: t\nblocks:\n  - {type: text_finding, id: f}\n")
    block = res.blocks[0]
    assert isinstance(block, TextFindingResult) and block.markdown is None
    many = InMemoryReportDataSource(
        weights=ref.daily,
        days=days_from_reference(ref),
        settings=settings_for(ref),
        findings={"agent": "Summary\n" + "\n".join(f"- point {i}" for i in range(8))},
    )
    res = _render(
        many,
        ref,
        "name: t\ntitle: t\nblocks:\n"
        "  - {type: text_finding, id: f, source: agent, max_items: 5}\n",
    )
    block = res.blocks[0]
    assert isinstance(block, TextFindingResult) and block.markdown is not None
    assert block.markdown.count("- point") == 5 and block.markdown.startswith("Summary")


def test_missing_weights_degrade_to_block_errors(ref: Reference) -> None:
    source = InMemoryReportDataSource(
        weights={},
        days=days_from_reference(ref),
        settings=settings_for(ref),
        findings={"agent": "ok"},
    )
    res = ReportEngine(source).render(
        ReportRegistry().get("checkup"),
        Period(ref.today - timedelta(days=13), ref.today),
        ref.today,
    )
    kinds = {type(b).__name__ for b in res.blocks}
    assert "DayListResult" in kinds and "TextFindingResult" in kinds
    errored = {b.meta.type for b in res.errors}
    assert {"tdee_windows", "trend", "forecast", "burndown"} <= errored
    weight_tile = next(
        b for b in res.blocks if isinstance(b, KpiTileResult) and b.source == "weight.ma7"
    )
    assert weight_tile.value is None  # no data is not an error for a tile


def test_only_countable_days_feed_averages(ref: Reference) -> None:
    days = days_from_reference(ref)
    period = Period(ref.today - timedelta(days=13), ref.today)
    in_period = [d for d in days if period.start <= d <= period.end]
    victim = in_period[0]
    days[victim] = DayMacros(
        victim, Macros(kcal=99999.0), DayStatus.CLOSED, False, None, countable=False
    )
    source = InMemoryReportDataSource(weights=ref.daily, days=days, settings=settings_for(ref))
    res = ReportEngine(source).render(
        load_definition(
            "name: t\ntitle: t\nblocks:\n  - {type: kpi_tile, id: k, source: kcal.average}\n"
        ),
        period,
        ref.today,
    )
    tile = res.blocks[0]
    assert isinstance(tile, KpiTileResult)
    expected = sum(ref.calories[d] for d in in_period[1:]) / len(in_period[1:])
    assert tile.value == round(expected)


def test_default_period_and_dates_never_leak_future(ref: Reference) -> None:
    source = InMemoryReportDataSource(
        weights=ref.daily, days=days_from_reference(ref), settings=settings_for(ref)
    )
    earlier = ref.today - timedelta(days=60)
    res = ReportEngine(source).render(
        load_definition(
            "name: t\ntitle: t\nblocks:\n  - {type: kpi_tile, id: k, source: weight.latest}\n"
        ),
        today=earlier,
    )
    assert res.period.end == earlier and res.period.days == 14
    tile = res.blocks[0]
    assert isinstance(tile, KpiTileResult)
    assert tile.note is not None
    assert date.fromisoformat(str(tile.note.params["date"])) <= earlier
