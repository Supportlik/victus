"""Shared loaders for the frozen synthetic reference (tests/fixtures/tdee_reference.json)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "tdee_reference.json"


def _series(raw: dict[str, float]) -> dict[date, float]:
    return {date.fromisoformat(k): float(v) for k, v in raw.items()}


class Reference:
    def __init__(self, data: dict[str, Any]) -> None:
        self.raw = data
        p = data["params"]
        self.kcal_per_kg: float = p["kcal_per_kg"]
        self.ma_days: int = p["ma_days"]
        self.goal_kg: float = p["goal_kg"]
        self.goal_date = date.fromisoformat(p["goal_date"])
        self.corridor: tuple[int, int] = (p["corridor"][0], p["corridor"][1])
        self.windows: list[int] = p["windows"]
        self.trend_windows: list[int] = p["trend_windows"]
        self.today = date.fromisoformat(p["today"])
        self.burndown_start = date.fromisoformat(p["burndown_start"])
        self.stages = [(s["name"], date.fromisoformat(s["date"])) for s in p["stages"]]
        self.protein_band = p["protein_band"]
        i = data["inputs"]
        self.daily = _series(i["daily"])
        self.calories = _series(i["calories"])
        self.protein = _series(i["protein"])
        self.out = data["outputs"]


@pytest.fixture(scope="session")
def ref() -> Reference:
    return Reference(json.loads(FIXTURE.read_text(encoding="utf-8")))
