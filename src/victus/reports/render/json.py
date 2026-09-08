"""``ReportResult`` → plain JSON-serialisable dict (dates ISO, enums as values)."""

from __future__ import annotations

import dataclasses
import enum
from datetime import date, datetime
from typing import Any

from victus.reports.results import BlockError, ReportResult


def _convert(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _convert(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(_convert(k)): _convert(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_convert(v) for v in value]
    if isinstance(value, float) and value != value:  # NaN guard
        return None
    return value


def to_dict(result: ReportResult) -> dict[str, Any]:
    """Convert a result tree; every block carries ``meta.type`` and an ``error`` flag."""
    data: dict[str, Any] = _convert(result)
    for block, raw in zip(data["blocks"], result.blocks, strict=True):
        block["error"] = isinstance(raw, BlockError)
    data["period"] = {
        "start": result.period.start.isoformat(),
        "end": result.period.end.isoformat(),
        "days": result.period.days,
    }
    return data
