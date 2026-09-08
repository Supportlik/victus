"""Total daily energy expenditure — two deliberate methods (SPEC R34).

* ``weekly_tdee``: the predecessor's nSuns-style weekly table, smoothed with the
  previous week.
* ``rolling_tdee``: energy balance over a rolling window of *calendar* days with
  the weight delta taken from the moving average; each window carries a quality
  grade (``reliability.grade``).

Divergence between the two is a signal ("not reliable"), not a bug.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from victus.domain.model.reporting import RequiredRate, RollingRow, WeekRow
from victus.domain.services.reliability import grade
from victus.domain.values import CalorieCorridor

PLAUSIBLE_MIN = 1000
PLAUSIBLE_MAX = 6000


def _plausible(tdee: int) -> bool:
    return PLAUSIBLE_MIN <= tdee <= PLAUSIBLE_MAX


def weekly_tdee(
    daily: Mapping[date, float],
    calories: Mapping[date, float],
    kcal_per_kg: float,
) -> list[WeekRow]:
    """Per Monday-based week: mean kg, mean kcal, Δkg to the previous week, TDEE.

    ``raw = mean_kcal + (−Δkg × kcal_per_kg) / days_with_kcal`` and
    ``tdee = round((raw + previous_tdee) / 2)`` (or ``round(raw)`` for the first
    week). Values outside 1000–6000 are discarded (``None``).
    """
    buckets: dict[date, dict[str, list[float]]] = {}
    for d, w in daily.items():
        key = d - timedelta(days=d.weekday())
        buckets.setdefault(key, {"w": [], "c": []})["w"].append(w)
    for d, c in calories.items():
        key = d - timedelta(days=d.weekday())
        buckets.setdefault(key, {"w": [], "c": []})["c"].append(c)

    rows: list[WeekRow] = []
    prev_w: float | None = None
    prev_tdee: int | None = None
    for key in sorted(buckets):
        b = buckets[key]
        avg_w = round(statistics.mean(b["w"]), 2) if b["w"] else None
        avg_c = round(statistics.mean(b["c"])) if b["c"] else None
        n_c = len(b["c"])
        delta = round(avg_w - prev_w, 2) if (avg_w and prev_w) else None

        tdee: int | None = None
        if avg_c and delta is not None and n_c:
            raw = avg_c + ((-delta) * kcal_per_kg) / n_c
            tdee = round((raw + prev_tdee) / 2) if prev_tdee else round(raw)
            if not _plausible(tdee):
                tdee = None
        rows.append(
            WeekRow(
                week_start=key,
                mean_kg=avg_w,
                delta_kg=delta,
                mean_kcal=float(avg_c) if avg_c is not None else None,
                days_with_kcal=n_c,
                tdee=tdee,
            )
        )
        if avg_w:
            prev_w = avg_w
        if tdee:
            prev_tdee = tdee
    return rows


def rolling_window(
    daily: Mapping[date, float],
    ma: Mapping[date, float],
    calories: Mapping[date, float],
    protein: Mapping[date, float],
    days: int,
    kcal_per_kg: float,
    corridor: CalorieCorridor,
    end: date | None = None,
) -> RollingRow | None:
    """One rolling window ending at ``end`` (default: last MA date).

    Energy balance: ``TDEE × D = intake + lost kg × kcal_per_kg`` →
    ``TDEE = mean_kcal + (lost kg × kcal_per_kg) / D`` with ``D`` = calendar days.
    Untracked days are implicitly set to the mean of the tracked ones. The weight
    delta comes from the moving average, never from raw values.
    """
    if not ma:
        return None
    last = end or max(ma)
    start = last - timedelta(days=days)
    ma_pts = sorted((d, v) for d, v in ma.items() if start <= d <= last)
    delta = round(ma_pts[-1][1] - ma_pts[0][1], 2) if len(ma_pts) >= 2 else None
    span = (ma_pts[-1][0] - ma_pts[0][0]).days if len(ma_pts) >= 2 else 0

    window = [start + timedelta(days=i) for i in range(1, days + 1)]
    kc = [calories[d] for d in window if d in calories]
    coverage = round(100 * len(kc) / days)
    mean_kcal = round(statistics.mean(kc)) if kc else None
    measured = sum(1 for d in window if d in daily)
    in_corr = sum(
        1 for d in window if d in calories and corridor.min <= calories[d] <= corridor.max
    )
    above = sum(1 for d in window if d in calories and calories[d] > corridor.max)
    below = sum(1 for d in window if d in calories and calories[d] < corridor.min)
    without_macros = sum(1 for d in window if d in calories and d not in protein)
    pr = [protein[d] for d in window if d in protein]
    mean_protein = round(statistics.mean(pr)) if pr else None

    tdee: int | None = None
    rejected: int | None = None
    quality = None
    if mean_kcal is not None and delta is not None and span >= 2:
        candidate = round(mean_kcal + ((-delta) * kcal_per_kg) / days)
        if _plausible(candidate):
            tdee = candidate
        else:
            rejected = candidate
        quality = grade(days, coverage, without_macros)

    return RollingRow(
        window_days=days,
        start=start,
        end=last,
        mean_kcal=mean_kcal,
        delta_ma_kg=delta,
        tdee=tdee,
        rejected_tdee=rejected,
        coverage_pct=coverage,
        days_with_kcal=len(kc),
        measured_days=measured,
        days_without_macros=without_macros,
        in_corridor=in_corr,
        above_corridor=above,
        below_corridor=below,
        mean_protein=mean_protein,
        quality=quality,
    )


def rolling_tdee(
    daily: Mapping[date, float],
    ma: Mapping[date, float],
    calories: Mapping[date, float],
    protein: Mapping[date, float],
    windows: Sequence[int],
    kcal_per_kg: float,
    corridor: CalorieCorridor,
    end: date | None = None,
) -> list[RollingRow]:
    rows: list[RollingRow] = []
    for w in windows:
        row = rolling_window(daily, ma, calories, protein, w, kcal_per_kg, corridor, end)
        if row is not None:
            rows.append(row)
    return rows


def reference_tdee(
    weeks: Sequence[WeekRow], rolling: Sequence[RollingRow]
) -> tuple[int | None, str]:
    """The value that steers goal arithmetic: rolling 14-day TDEE, else the mean of
    the last eight weekly values. Returns ``(tdee, basis)``."""
    r14 = next((r.tdee for r in rolling if r.window_days == 14 and r.tdee), None)
    if r14 is not None:
        return r14, "rolling_14d"
    tdees = [w.tdee for w in weeks[-8:] if w.tdee]
    if tdees:
        return round(statistics.mean(tdees)), "weekly_mean_8w"
    return None, "none"


def implied_tdee(
    weights: Mapping[date, float],
    calories: Sequence[float],
    kcal_per_kg: float,
) -> float | None:
    """Predecessor ``status.py``: ``mean(kcal) + (−Δkg over the window × kcal_per_kg) / n_kcal``.

    ``weights`` are the raw measurements inside the window (first and last are
    used), ``calories`` the logged kcal values inside it.
    """
    if len(weights) < 2 or not calories:
        return None
    ds = sorted(weights)
    delta = weights[ds[-1]] - weights[ds[0]]
    return statistics.mean(calories) + ((-delta) * kcal_per_kg) / len(calories)


def required_rate(
    current_kg: float,
    goal_kg: float,
    goal_date: date,
    today: date,
    kcal_per_kg: float,
) -> RequiredRate:
    """Rate and daily deficit needed to reach ``goal_kg`` by ``goal_date``."""
    days_left = max((goal_date - today).days, 1)
    slope = (goal_kg - current_kg) / days_left
    return RequiredRate(
        kg_per_week=slope * 7,
        deficit_kcal_per_day=-slope * kcal_per_kg,
        days_left=days_left,
        to_go_kg=current_kg - goal_kg,
    )


def eat_target(tdee_ref: int | None, required: RequiredRate) -> int | None:
    """Daily intake that produces the required deficit under ``tdee_ref``."""
    if tdee_ref is None:
        return None
    return round(tdee_ref - required.deficit_kcal_per_day)
