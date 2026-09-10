"""DTO → response model helpers (keeps the routers declarative)."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from victus.api.schemas.common import (
    DayOut,
    DaySummaryOut,
    FindingOut,
    LineItemOut,
    MacrosOut,
    MealOut,
    MessageOut,
    TargetBandOut,
)
from victus.application import dto


def _plain(obj: Any) -> Any:
    return asdict(obj) if is_dataclass(obj) and not isinstance(obj, type) else obj


def line_item_out(li: dto.LineItemView) -> LineItemOut:
    return LineItemOut.model_validate(li)


def meal_out(m: dto.MealView) -> MealOut:
    return MealOut(
        id=m.id,
        position=m.position,
        name=m.name,
        time=m.time,
        line_items=[line_item_out(li) for li in m.line_items],
        totals=MacrosOut.from_macros(m.totals),
    )


def target_band_out(tb: dto.TargetBandView | None) -> TargetBandOut | None:
    return TargetBandOut.model_validate(_plain(tb)) if tb is not None else None


def day_summary_out(d: dto.DaySummaryView) -> DaySummaryOut:
    return DaySummaryOut(
        date=d.date,
        status=d.status,
        reliable=d.reliable,
        training_type=d.training_type,
        macros=MacrosOut.from_macros(d.macros),
        has_drafts=d.has_drafts,
        weight_kg=d.weight_kg,
    )


def day_out(d: dto.DayView) -> DayOut:
    return DayOut(
        date=d.date,
        status=d.status,
        reliable=d.reliable,
        training_type=d.training_type,
        macros=MacrosOut.from_macros(d.macros),
        has_drafts=d.has_drafts,
        weight_kg=d.weight_kg,
        weekday=d.weekday,
        meals=[meal_out(m) for m in d.meals],
        target_band=target_band_out(d.target_band),
        zones={k: v.value for k, v in d.zones.items()},
        findings=[
            FindingOut(
                kind=f.kind,
                code=f.code,
                message=MessageOut(key=f.message.key, params=dict(f.message.params)),
            )
            for f in d.findings
        ],
        notes=d.notes,
        verdict=d.verdict,
    )
