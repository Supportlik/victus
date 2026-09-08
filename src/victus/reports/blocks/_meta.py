from __future__ import annotations

from victus.reports.definition import _BlockBase
from victus.reports.results import BlockMeta

DEFAULT_TITLES: dict[str, str] = {
    "kpi_tile": "Key figure",
    "band_distribution": "Target bands",
    "tdee_windows": "TDEE",
    "trend": "Trend",
    "forecast": "Forecast",
    "burndown": "Burndown",
    "weekly_chart": "Weeks",
    "day_list": "Days",
    "text_finding": "Finding",
}


def meta_for(block: _BlockBase) -> BlockMeta:
    block_type = str(getattr(block, "type", "unknown"))
    return BlockMeta(
        type=block_type,
        id=block.id,
        title=block.title or DEFAULT_TITLES.get(block_type, block_type),
    )
