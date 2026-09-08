"""Weight trend: moving average, regression slope, per-window trends, yearly stats.

Ported 1:1 from the predecessor's report script; every rounding is kept so the
frozen reference values (``tests/fixtures/tdee_reference.json``) reproduce.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from victus.domain.model.reporting import TrendRow, YearRow


def moving_average(series: Mapping[date, float], n: int) -> dict[date, float]:
    """Backward moving average over ``n`` *calendar* days; gaps are simply absent.

    For each measured day the mean of all measurements within the last ``n``
    calendar days (inclusive) is taken and rounded to 2 decimals.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    out: dict[date, float] = {}
    for d in sorted(series):
        lo = d - timedelta(days=n - 1)
        vals = [v for dd, v in series.items() if lo <= dd <= d]
        if vals:
            out[d] = round(statistics.mean(vals), 2)
    return out


def regression_slope(points: Sequence[tuple[date, float]]) -> float | None:
    """Least-squares slope in kg/day; ``None`` with fewer than 3 points or zero spread."""
    if len(points) < 3:
        return None
    x0 = points[0][0]
    xs = [(d - x0).days for d, _ in points]
    ys = [v for _, v in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom


def slope_for_window(ma: Mapping[date, float], days: int) -> tuple[float | None, int]:
    """Predecessor ``trend_per_day``: regression over MA points with ``d >= last - days``.

    Note the window is ``days`` calendar days *back from the last point*, which
    covers ``days + 1`` dates — kept for reference compatibility.
    """
    if not ma:
        return None, 0
    last = max(ma)
    items = sorted((d, v) for d, v in ma.items() if d >= last - timedelta(days=days))
    return regression_slope(items), len(items)


def trend_windows(
    ma: Mapping[date, float],
    daily: Mapping[date, float],
    windows: Sequence[int],
    today: date | None = None,
) -> list[TrendRow]:
    """Per window: regression slope plus the actual MA difference inside the window."""
    out: list[TrendRow] = []
    if not ma:
        return out
    end = today or max(ma)
    for w in windows:
        slope, n = slope_for_window(ma, w)
        since = end - timedelta(days=w - 1)
        window_pts = sorted((d, v) for d, v in ma.items() if d >= since)
        diff = round(window_pts[-1][1] - window_pts[0][1], 2) if len(window_pts) >= 2 else None
        measured = sum(1 for d in daily if d >= since)
        out.append(
            TrendRow(
                window=w,
                slope_per_day=slope,
                kg_per_week=round(slope * 7, 2) if slope is not None else None,
                actual_delta=diff,
                start=since,
                end=end,
                points=n,
                measured_days=measured,
            )
        )
    return out


def yearly_stats(daily: Mapping[date, float]) -> list[YearRow]:
    by_year: dict[int, list[tuple[date, float]]] = {}
    for d, v in daily.items():
        by_year.setdefault(d.year, []).append((d, v))
    rows: list[YearRow] = []
    for year in sorted(by_year):
        pts = sorted(by_year[year])
        vals = [v for _, v in pts]
        rows.append(
            YearRow(
                year=year,
                start=pts[0][1],
                start_date=pts[0][0],
                end=pts[-1][1],
                end_date=pts[-1][0],
                delta=round(pts[-1][1] - pts[0][1], 2) if len(pts) >= 2 else None,
                min=min(vals),
                max=max(vals),
                mean=round(statistics.mean(vals), 2),
                measured_days=len(pts),
            )
        )
    return rows
