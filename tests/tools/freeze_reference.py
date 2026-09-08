#!/usr/bin/env python3
"""Freeze reference values for the reporting domain services from the *predecessor's*
formulas, computed on a **synthetic** data set.

Why synthetic: the repository must not contain personal data (SPEC R48). The
predecessor's scripts are private and are only needed once, here, to produce
numbers the new implementation has to reproduce. The generated series is
deterministic (fixed seed) and has nothing to do with any real person.

Usage::

    VICTUS_LEGACY_SCRIPTS=/path/to/gewicht-report/scripts \\
        uv run python tests/tools/freeze_reference.py

Writes ``tests/fixtures/tdee_reference.json``. Re-freeze only when the *formula*
changes on purpose; a failing test is a finding, not a reason to re-freeze.
"""

from __future__ import annotations

import ast
import json
import os
import random
import statistics
import sys
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / "fixtures" / "tdee_reference.json"
DEFAULT_LEGACY = ""  # set VICTUS_LEGACY_SCRIPTS to the predecessor scripts directory

SEED = 20260908
KCAL_PER_KG = 7716.17
MA_DAYS = 7
GOAL_KG = 82.0
GOAL_DATE = date(2026, 12, 31)
CORRIDOR = (1800, 2200)
PROTEIN_TARGET = 150
WINDOWS = [3, 7, 14, 21, 30, 60, 90]
TREND_WINDOWS = [7, 14, 21, 30, 60, 90]
PROTEIN_BAND = {"min": 105, "opt": [150, 185], "max": 200}
BURNDOWN_START = date(2026, 3, 1)
STAGES = [("Stretch", date(2026, 10, 31)), ("Target", GOAL_DATE), ("Minimum", date(2027, 2, 28))]


def synthetic_series() -> tuple[dict[date, float], dict[date, float], dict[date, float]]:
    rng = random.Random(SEED)
    start = date(2025, 11, 20)
    daily: dict[date, float] = {}
    cals: dict[date, float] = {}
    prot: dict[date, float] = {}
    weight = 96.0
    for i in range(220):
        d = start + timedelta(days=i)
        weight += -0.045 + rng.gauss(0, 0.05)  # slow downward trend
        if rng.random() > 0.12:  # 12 % gaps in weighing
            daily[d] = round(weight + rng.gauss(0, 0.6), 2)
        if rng.random() > 0.15:  # 15 % days without a log
            kcal = float(rng.randint(1400, 3200))
            cals[d] = kcal
            if rng.random() > 0.15:  # some logs without macros
                prot[d] = float(rng.randint(90, 210))
    return daily, cals, prot


def _extract(source: str, names: set[str]) -> str:
    """Return the source of the top-level (or nested) function defs named in ``names``."""
    tree = ast.parse(source)
    chunks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            chunks.append(ast.unparse(node))
    found = {n for n in names if any(f"def {n}(" in c for c in chunks)}
    missing = names - found
    if missing:
        raise SystemExit(f"functions not found in legacy script: {sorted(missing)}")
    return "\n\n".join(chunks)


def load_legacy(scripts_dir: Path, today: date) -> dict[str, Any]:
    ns: dict[str, Any] = {
        "statistics": statistics,
        "timedelta": timedelta,
        "date": date,
        "datetime": datetime,
        "OrderedDict": OrderedDict,
        "KCAL_KG": KCAL_PER_KG,
        "MA_N": MA_DAYS,
        "ZIEL_KG": GOAL_KG,
        "ZIEL_DATUM": GOAL_DATE,
        "CFG": {"kalorien_korridor": list(CORRIDOR), "eiweiss_ziel": PROTEIN_TARGET},
        "TREND_FENSTER": [(w, f"{w}d") for w in TREND_WINDOWS],
    }
    report_src = (scripts_dir / "build_report.py").read_text(encoding="utf-8")
    status_src = (scripts_dir / "status.py").read_text(encoding="utf-8")
    code = _extract(
        report_src,
        {
            "moving_average",
            "weekly_stats",
            "rolling_tdee",
            "trend_per_day",
            "trend_table",
            "prognose_table",
            "yearly_stats",
        },
    )
    code += "\n\n" + _extract(status_src, {"band_verteilung"})
    exec(compile(code, "<legacy>", "exec"), ns)  # trusted local script
    return ns


def _d(x: Any) -> Any:
    if isinstance(x, dict):
        return {(_k.isoformat() if isinstance(_k, date) else _k): _d(v) for _k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_d(v) for v in x]
    if isinstance(x, date):
        return x.isoformat()
    return x


def main() -> int:
    scripts = Path(os.environ.get("VICTUS_LEGACY_SCRIPTS", DEFAULT_LEGACY))
    daily, cals, prot = synthetic_series()
    today = max(daily)
    legacy = load_legacy(scripts, today)

    ma = legacy["moving_average"](daily, MA_DAYS)
    weeks = legacy["weekly_stats"](daily, cals)
    rolling = {str(w): legacy["rolling_tdee"](daily, ma, cals, prot, w) for w in WINDOWS}
    trends = legacy["trend_table"](ma, daily)
    cur = ma[today]
    prog = legacy["prognose_table"](trends, cur, today)
    years = legacy["yearly_stats"](daily)
    prot_values = sorted(prot.values())
    u, rest, g, o = legacy["band_verteilung"](prot_values, PROTEIN_BAND)

    # Burndown reference: the predecessor computed these inline in build(); the
    # formulas are reproduced here verbatim (see docs/TESTPLAN.md, T-DOM-009).
    anchor = min(d for d in ma if d >= BURNDOWN_START)
    rest0 = ma[anchor] - GOAL_KG
    el = (today - anchor).days
    bd_ist = ma[today] - GOAL_KG
    bd = {
        "anchor": anchor,
        "rest0": rest0,
        "ist": bd_ist,
        "soll": rest0 * (1 - el / max((GOAL_DATE - anchor).days, 1)),
        "abgebaut": rest0 - bd_ist,
        "tage": el,
        "rate_ist": (rest0 - bd_ist) / (el / 7) if el else 0.0,
        "rate_soll": rest0 / max((GOAL_DATE - anchor).days / 7, 1),
        "rate_noetig": bd_ist / max((GOAL_DATE - today).days / 7, 1),
        "stufen": [],
    }
    bd["delta"] = bd["soll"] - bd_ist
    for name, zd in sorted(STAGES, key=lambda s: s[1]):
        if not anchor < zd:
            continue
        tage = (zd - anchor).days
        soll_ = rest0 * (1 - el / tage)
        rest_wo = max((zd - today).days / 7, 0.01)
        rate_ = bd_ist / rest_wo
        bd["stufen"].append(
            {
                "name": name,
                "datum": zd,
                "soll": soll_,
                "delta": soll_ - bd_ist,
                "rate_noetig": rate_,
                "pct": rate_ / cur * 100,
            }
        )

    # Guete strings → enum names
    for rows in rolling.values():
        if rows and rows.get("guete"):
            rows["quality"] = {"🔴": "red", "🟡": "yellow", "🟢": "green"}[rows["guete"][0]]

    fixture = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": SEED,
        "note": "Synthetic series (random walk with trend, gaps) — no real person's data. "
        "Outputs computed with the predecessor's formulas.",
        "params": {
            "kcal_per_kg": KCAL_PER_KG,
            "ma_days": MA_DAYS,
            "goal_kg": GOAL_KG,
            "goal_date": GOAL_DATE,
            "corridor": list(CORRIDOR),
            "protein_target": PROTEIN_TARGET,
            "windows": WINDOWS,
            "trend_windows": TREND_WINDOWS,
            "protein_band": PROTEIN_BAND,
            "burndown_start": BURNDOWN_START,
            "stages": [{"name": n, "date": d} for n, d in STAGES],
            "today": today,
        },
        "inputs": {"daily": daily, "calories": cals, "protein": prot},
        "outputs": {
            "moving_average": ma,
            "weekly": weeks,
            "rolling": rolling,
            "trends": trends,
            "forecast": prog,
            "years": years,
            "protein_distribution": {
                "below_min": u,
                "between": rest,
                "optimal": g,
                "above_max": o,
                "n": len(prot_values),
            },
            "burndown": bd,
        },
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(_d(fixture), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {FIXTURE} ({len(daily)} weigh-ins, {len(cals)} logged days, today={today})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
