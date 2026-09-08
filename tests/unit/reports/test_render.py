"""T-RPT-012 / T-RPT-013: Markdown and JSON renderers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.domain.conftest import Reference
from tests.unit.reports.conftest import settings_for
from victus.domain.values import Period
from victus.reports.engine import ReportEngine
from victus.reports.memory_source import InMemoryReportDataSource
from victus.reports.registry import ReportRegistry
from victus.reports.render.json import to_dict
from victus.reports.render.markdown import num, signed, to_markdown

pytestmark = pytest.mark.reports


@pytest.fixture
def checkup(source: InMemoryReportDataSource, ref: Reference):  # type: ignore[no-untyped-def]
    return ReportEngine(source).render(
        ReportRegistry().get("checkup"),
        Period(ref.today - timedelta(days=13), ref.today),
        ref.today,
        now=datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    )


def test_number_formatting() -> None:
    assert num(2610, 0, "kcal") == "2,610 kcal"
    assert num(86.44, 1, "kg") == "86.4 kg"
    assert num(None) == "–"
    assert signed(-0.45, 2, "kg/week") == "-0.45 kg/week"
    assert signed(0.3) == "+0.30"


def test_markdown_structure(checkup) -> None:  # type: ignore[no-untyped-def]
    md = to_markdown(checkup)
    assert md.startswith("## Am I on track?")
    assert "generated 2026-09-08 12:00 UTC" in md
    # KPI tiles come first as a bullet list, then one heading per block.
    assert "- **Weight (moving average):**" in md
    for heading in (
        "### TDEE",
        "### Target bands",
        "### Trend",
        "### Forecast",
        "### Burndown",
        "### Days",
    ):
        assert heading in md, heading
    assert "| Window | Ø kcal | Δ kg (MA) | TDEE | Coverage | Quality |" in md
    assert "| Macro | Days | Mean | Band min / opt / max |" in md
    assert "Reference TDEE: **" in md
    assert any(e in md for e in ("🟢", "🟡", "🔴"))
    assert "- first" in md  # agent finding rendered verbatim


def test_markdown_shows_block_errors_without_crashing(ref: Reference) -> None:
    source = InMemoryReportDataSource(weights={}, days={}, settings=settings_for(ref))
    res = ReportEngine(source).render(ReportRegistry().get("checkup"), today=ref.today)
    md = to_markdown(res)
    assert "⚠️" in md and "_No finding recorded._" in md


def test_json_round_trip(checkup) -> None:  # type: ignore[no-untyped-def]
    data = to_dict(checkup)
    text = json.dumps(data)  # must not raise
    back = json.loads(text)
    assert back["name"] == "checkup"
    assert back["period"] == {
        "start": checkup.period.start.isoformat(),
        "end": checkup.period.end.isoformat(),
        "days": 14,
    }
    assert back["generated_at"].startswith("2026-09-08T12:00")
    assert all("error" in b and "meta" in b for b in back["blocks"])
    assert not any(b["error"] for b in back["blocks"])
    tdee = next(b for b in back["blocks"] if b["meta"]["type"] == "tdee_windows")
    assert tdee["rows"][0]["quality"] in {"red", "yellow", "green", None}
    assert isinstance(tdee["rows"][0]["start"], str)
