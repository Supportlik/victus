"""T-RPT-001 / T-RPT-002 / T-RPT-003: parsing, rejection of garbage, schema-valid built-in."""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from pathlib import Path

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

from victus.reports.definition import (
    DayListDef,
    ForecastDef,
    KpiTileDef,
    WeeklyChartDef,
    load_definition,
    parse_period_token,
)
from victus.reports.registry import ReportRegistry, load_builtins

pytestmark = pytest.mark.reports

ROOT = Path(__file__).resolve().parents[3]

FULL = """
name: everything
title: Every block
blocks:
  - {type: kpi_tile, id: w, source: weight.ma7}
  - {type: band_distribution, macros: [kcal, protein]}
  - {type: tdee_windows}
  - {type: trend}
  - {type: forecast}
  - {type: burndown}
  - {type: weekly_chart}
  - {type: day_list}
  - {type: text_finding, id: f}
"""


def test_parse_every_block_type_with_defaults() -> None:
    d = load_definition(FULL)
    assert d.name == "everything"
    assert d.period.default == "14d"
    assert [b.type for b in d.blocks] == [
        "kpi_tile",
        "band_distribution",
        "tdee_windows",
        "trend",
        "forecast",
        "burndown",
        "weekly_chart",
        "day_list",
        "text_finding",
    ]
    fc = next(b for b in d.blocks if isinstance(b, ForecastDef))
    assert fc.horizons == ["1m", "3m", "6m"] and fc.with_eta is True
    dl = next(b for b in d.blocks if isinstance(b, DayListDef))
    assert dl.columns == ["kcal", "protein", "fiber", "weight", "status"] and dl.limit == 14
    wc = next(b for b in d.blocks if isinstance(b, WeeklyChartDef))
    assert wc.series == ["kcal", "tdee"] and wc.weeks == 12
    kpi = next(b for b in d.blocks if isinstance(b, KpiTileDef))
    assert kpi.source == "weight.ma7"


@pytest.mark.parametrize(
    "snippet",
    [
        "name: x\ntitle: t\nblocks:\n  - {type: pie}\n",
        "name: x\ntitle: t\nblocks:\n  - {type: kpi_tile, id: 'Bad Id', source: weight.ma7}\n",
        "name: Bad Name\ntitle: t\nblocks:\n  - {type: trend}\n",
        "name: x\ntitle: t\nperiod: {default: fortnight}\nblocks:\n  - {type: trend}\n",
        "name: x\ntitle: t\nblocks:\n  - {type: kpi_tile, id: w, source: nonsense}\n",
        "name: x\ntitle: t\nblocks: []\n",
        "name: x\ntitle: t\nblocks:\n  - {type: trend, colour: red}\n",
    ],
)
def test_invalid_definitions_are_rejected(snippet: str) -> None:
    with pytest.raises(ValidationError):
        load_definition(snippet)


def test_period_token() -> None:
    p = parse_period_token("14d", date(2026, 3, 14))
    assert p.start == date(2026, 3, 1) and p.end == date(2026, 3, 14) and p.days == 14
    with pytest.raises(ValueError):
        parse_period_token("custom", date(2026, 3, 14))


def test_builtin_checkup_is_schema_valid_and_registered() -> None:
    schema = json.loads((ROOT / "schemas" / "report-definition.schema.json").read_text("utf-8"))
    raw = (resources.files("victus.reports.builtin") / "checkup.yaml").read_text("utf-8")
    jsonschema.validate(yaml.safe_load(raw), schema)
    names = [d.name for d in load_builtins()]
    assert names == ["checkup"]
    reg = ReportRegistry()
    assert reg.is_builtin("checkup") and reg.get("checkup").title == "Am I on track?"
    with pytest.raises(KeyError):
        reg.get("nope")


def test_tenant_loader_cannot_shadow_builtins() -> None:
    shadow = load_definition("name: checkup\ntitle: mine\nblocks:\n  - {type: trend}\n")
    mine = load_definition("name: mine\ntitle: mine\nblocks:\n  - {type: trend}\n")
    reg = ReportRegistry(tenant_loader=lambda: [shadow, mine])
    assert reg.get("checkup").title == "Am I on track?"
    assert [d.name for d in reg.list()] == ["checkup", "mine"]
