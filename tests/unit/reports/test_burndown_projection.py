"""T-RPT-100 … T-RPT-105: the burndown block's pace projections, in the block and both renderers."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from tests.unit.domain.conftest import Reference
from tests.unit.reports.conftest import settings_for
from victus.application.ports.report_data import TenantReportSettings
from victus.domain.model.reporting import Stage
from victus.domain.values import Period
from victus.reports.definition import BurndownDef, load_definition
from victus.reports.engine import ReportEngine
from victus.reports.memory_source import InMemoryReportDataSource
from victus.reports.render.json import to_dict
from victus.reports.render.markdown import to_markdown
from victus.reports.results import BurndownBlockResult, ForecastResult, ReportResult

pytestmark = pytest.mark.reports

ROOT = Path(__file__).resolve().parents[3]
BOTH = "name: t\ntitle: t\nblocks:\n  - {type: forecast}\n  - {type: burndown%s}\n"


def _render(source: InMemoryReportDataSource, today: date, extra: str = "") -> ReportResult:
    definition = load_definition(BOTH % extra)
    return ReportEngine(source).render(definition, Period(today - timedelta(days=13), today), today)


def _blocks(res: ReportResult) -> tuple[ForecastResult, BurndownBlockResult]:
    fc, bd = res.blocks
    assert isinstance(fc, ForecastResult) and isinstance(bd, BurndownBlockResult)
    return fc, bd


def test_projection_windows_parameter() -> None:
    """T-RPT-100: default [7, 14, 30]; [] switches it off; a window below 2 or twice is refused."""
    assert BurndownDef(type="burndown").projection_windows == [7, 14, 30]
    assert BurndownDef(type="burndown", projection_windows=[]).projection_windows == []
    for bad in ([1], [7, 7]):
        with pytest.raises(ValidationError):
            BurndownDef(type="burndown", projection_windows=bad)
    schema = json.loads((ROOT / "schemas" / "report-definition.schema.json").read_text("utf-8"))
    ok = {"name": "t", "title": "t", "blocks": [{"type": "burndown", "projection_windows": []}]}
    jsonschema.validate(ok, schema)
    for bad in ([1], [7, 7], ["7"]):
        doc = {
            "name": "t",
            "title": "t",
            "blocks": [{"type": "burndown", "projection_windows": bad}],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)


def test_block_crossing_equals_forecast_eta_on_the_reference(
    source: InMemoryReportDataSource, ref: Reference
) -> None:
    """T-RPT-101: default windows on the reference: 7/14 "not at this pace", 30 on its ETA."""
    fc, bd = _blocks(_render(source, ref.today))
    rows = bd.result.projections
    assert [p.window for p in rows] == [7, 14, 30]
    eta = {r.window: r.eta for r in fc.rows}
    frozen = {e["tage"]: e["eta"] for e in ref.out["forecast"]}
    for p in rows:
        assert p.crossing == eta[p.window]
        assert (p.crossing.isoformat() if p.crossing else None) == frozen[p.window]
    seven, fourteen, thirty = rows
    assert seven.crossing is None and seven.path == []
    assert fourteen.crossing is None and fourteen.path == []
    assert thirty.crossing is not None
    assert thirty.days_vs_goal == (thirty.crossing - ref.goal_date).days
    assert [s.name for s in thirty.stages] == [s.name for s in bd.result.stages]
    # zero lies beyond the last stage, so the dashed line stops at the chart's horizon
    assert thirty.path[0] == (ref.today, pytest.approx(bd.result.remaining_today))
    assert thirty.path[-1][0] == max(s.date for s in bd.result.stages)


def test_windows_follow_the_parameter(source: InMemoryReportDataSource, ref: Reference) -> None:
    """T-RPT-102: ``projection_windows: []`` drops the rows; [60, 90] yields the frozen ETAs."""
    _, off = _blocks(_render(source, ref.today, ", projection_windows: []"))
    assert off.result.projections == []
    assert off.result.stages  # the rest of the burndown is untouched
    _, bd = _blocks(_render(source, ref.today, ", projection_windows: [60, 90]"))
    frozen = {e["tage"]: e["eta"] for e in ref.out["forecast"]}
    got = {p.window: p.crossing.isoformat() for p in bd.result.projections if p.crossing}
    assert got == {60: frozen[60], 90: frozen[90]}


def test_crossing_is_measured_from_as_of_like_the_forecast(ref: Reference) -> None:
    """T-RPT-103: rendered three days after the last weigh-in, both blocks still name one day."""
    settings = settings_for(ref)
    source = InMemoryReportDataSource(weights=ref.daily, days={}, settings=settings)
    as_of = ref.today + timedelta(days=3)
    fc, bd = _blocks(_render(source, as_of, ", projection_windows: [30, 60, 90]"))
    eta = {r.window: r.eta for r in fc.rows}
    assert [p.crossing for p in bd.result.projections] == [eta[30], eta[60], eta[90]]
    assert all(p.path[0][0] == as_of for p in bd.result.projections)
    # three days later than the frozen render, the same slope lands three days later
    frozen = {e["tage"]: date.fromisoformat(e["eta"]) for e in ref.out["forecast"] if e["eta"]}
    for p in bd.result.projections:
        assert p.crossing == frozen[p.window] + timedelta(days=3)


def _falling_then_rising() -> InMemoryReportDataSource:
    """Synthetic: 50 days down 0.15 kg a day, then ten days up — every case in one report."""
    start = date(2026, 1, 1)
    weights = {start + timedelta(days=i): 95.0 - 0.15 * i for i in range(50)}
    weights.update({start + timedelta(days=50 + i): 87.65 + 0.1 * i for i in range(10)})
    settings = TenantReportSettings(
        goal_kg=85.0,
        goal_date=date(2026, 6, 30),
        stages=[Stage("Stretch", date(2026, 3, 15)), Stage("Target", date(2026, 6, 30))],
        burndown_start=start,
    )
    return InMemoryReportDataSource(weights=weights, days={}, settings=settings)


def test_markdown_pace_table() -> None:
    """T-RPT-104: one row per window with rate, zero day and early/late per date."""
    source = _falling_then_rising()
    today = date(2026, 3, 1)
    res = _render(source, today, ", projection_windows: [7, 30, 60]")
    _, bd = _blocks(res)
    seven, thirty, sixty = bd.result.projections
    assert seven.crossing is None  # rising at the end
    assert thirty.crossing is not None and sixty.crossing is not None
    md = to_markdown(res)
    assert "| Pace | kg/wk | Reaches zero | vs. goal | vs. Stretch | vs. Target |" in md
    assert f"| 7-day trend | {seven.kg_per_week:+.2f} | not at this pace | – | – | – |" in md
    for p in (thirty, sixty):
        assert p.crossing is not None and p.days_vs_goal is not None
        assert p.days_vs_goal < 0  # well before the end of June
        line = f"| {p.window}-day trend | {p.kg_per_week:+.2f} | {p.crossing.isoformat()} | "
        assert line + f"{-p.days_vs_goal} d early |" in md
        stretch = p.stages[0].days
        word = "late" if stretch > 0 else "early"
        assert (f"{abs(stretch)} d {word}" if stretch else "on time") in md
    off = to_markdown(_render(source, today, ", projection_windows: []"))
    assert "| Pace |" not in off


def test_json_carries_the_projection_rows() -> None:
    """T-RPT-105: ISO dates, ``null`` crossing for "not at this pace", the path as pairs."""
    res = _render(_falling_then_rising(), date(2026, 3, 1), ", projection_windows: [7, 30]")
    back = json.loads(json.dumps(to_dict(res)))
    bd = next(b for b in back["blocks"] if b["meta"]["type"] == "burndown")
    seven, thirty = bd["result"]["projections"]
    assert seven == {
        "window": 7,
        "slope_per_day": seven["slope_per_day"],
        "kg_per_week": seven["kg_per_week"],
        "crossing": None,
        "days_vs_goal": None,
        "stages": [],
        "path": [],
    }
    assert seven["slope_per_day"] > 0
    assert date.fromisoformat(thirty["crossing"]) < date(2026, 6, 30)
    assert thirty["days_vs_goal"] < 0
    assert [s["name"] for s in thirty["stages"]] == ["Stretch", "Target"]
    assert all(isinstance(s["days"], int) for s in thirty["stages"])
    first, last = thirty["path"]
    assert first[0] == "2026-03-01" and last == [thirty["crossing"], 0.0]
