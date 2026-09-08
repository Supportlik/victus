"""Quality grade of a rolling TDEE window (predecessor: ``guete`` in ``rolling_tdee``)."""

from __future__ import annotations

from victus.domain.values import Quality


def grade(days: int, coverage_pct: float, days_without_macros: int) -> Quality:
    """Short windows and tracking gaps make the value soft.

    * red: fewer than 7 days or coverage below 50 % — water dominates, the formula guesses
    * yellow: fewer than 14 days, coverage below 70 %, or two or more logged days without macros
    * green: otherwise
    """
    if days < 7 or coverage_pct < 50:
        return Quality.RED
    if days < 14 or coverage_pct < 70 or days_without_macros >= 2:
        return Quality.YELLOW
    return Quality.GREEN
