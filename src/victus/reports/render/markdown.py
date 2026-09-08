"""``ReportResult`` → Markdown for chats and the vault export.

This is the only place traffic-light emoji appear. Numbers use English
formatting (``2,610 kcal``, ``86.4 kg``).
"""

from __future__ import annotations

from datetime import date

from victus.domain.values import BandZone, Quality
from victus.reports.results import (
    BandDistributionResult,
    BlockError,
    BlockResult,
    BurndownBlockResult,
    DayListResult,
    ForecastResult,
    KpiTileResult,
    ReportResult,
    TdeeWindowsResult,
    TextFindingResult,
    TrendResult,
    WeeklyChartResult,
)

QUALITY_EMOJI: dict[Quality, str] = {
    Quality.GREEN: "🟢",
    Quality.YELLOW: "🟡",
    Quality.RED: "🔴",
}
ZONE_EMOJI: dict[BandZone, str] = {
    BandZone.OPTIMAL: "🟢",
    BandZone.BELOW_OPTIMUM: "🟡",
    BandZone.ABOVE_OPTIMUM: "🟡",
    BandZone.BELOW_MIN: "🔴",
    BandZone.ABOVE_MAX: "🔴",
}
ZONE_LABEL: dict[BandZone, str] = {
    BandZone.BELOW_MIN: "below min",
    BandZone.BELOW_OPTIMUM: "below optimum",
    BandZone.OPTIMAL: "optimal",
    BandZone.ABOVE_OPTIMUM: "above optimum",
    BandZone.ABOVE_MAX: "above max",
}


def num(value: float | int | None, decimals: int = 1, unit: str = "") -> str:
    if value is None:
        return "–"
    text = f"{value:,.{decimals}f}"
    return f"{text} {unit}".rstrip()


def signed(value: float | None, decimals: int = 2, unit: str = "") -> str:
    if value is None:
        return "–"
    return f"{value:+,.{decimals}f} {unit}".rstrip()


def _d(value: date | None) -> str:
    return value.isoformat() if value else "–"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out.extend("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join(out)


def _kpi(b: KpiTileResult) -> str:
    light = ""
    if b.quality is not None:
        light = " " + QUALITY_EMOJI[b.quality]
    elif b.zone is not None:
        light = " " + ZONE_EMOJI[b.zone]
    delta = f" ({signed(b.delta, b.decimals)} vs. previous period)" if b.delta is not None else ""
    note = f" · {b.note}" if b.note else ""
    return f"**{b.meta.title}:** {num(b.value, b.decimals, b.unit)}{light}{delta}{note}"


def _band_distribution(b: BandDistributionResult) -> str:
    rows: list[list[str]] = []
    for r in b.rows:
        s = r.stat
        band = "–"
        if r.band:
            band = (
                f"{num(r.band.min, 0)} / {num(r.band.opt_min, 0)}–{num(r.band.opt_max, 0)}"
                f" / {num(r.band.max, 0)}"
            )
        rows.append(
            [
                r.macro,
                str(s.n),
                num(s.mean, 1),
                band,
                str(s.below_min),
                str(s.below_optimum),
                f"**{s.optimal}**",
                str(s.above_optimum),
                str(s.above_max),
            ]
        )
    return _table(
        [
            "Macro",
            "Days",
            "Mean",
            "Band min / opt / max",
            "< min",
            "< opt",
            "optimal",
            "> opt",
            "> max",
        ],
        rows,
    )


def _tdee(b: TdeeWindowsResult) -> str:
    headers = ["Window", "Ø kcal", "Δ kg (MA)", "TDEE", "Coverage"]
    if b.show_quality:
        headers.append("Quality")
    rows: list[list[str]] = []
    for r in b.rows:
        row = [
            f"{r.window_days} d",
            num(r.mean_kcal, 0),
            signed(r.delta_ma_kg, 2),
            num(r.tdee, 0, "kcal")
            if r.tdee is not None
            else f"– (rejected {num(r.rejected_tdee, 0)})"
            if r.rejected_tdee is not None
            else "–",
            f"{r.coverage_pct} % ({r.days_with_kcal}/{r.window_days})",
        ]
        if b.show_quality:
            row.append(f"{QUALITY_EMOJI[r.quality]} {r.quality.value}" if r.quality else "–")
        rows.append(row)
    ref = f"\n\nReference TDEE: **{num(b.reference_tdee, 0, 'kcal')}** ({b.reference_basis})"
    return _table(headers, rows) + ref


def _trend(b: TrendResult) -> str:
    rows = [
        [
            f"{r.window} d",
            signed(r.kg_per_week, 2, "kg/week"),
            signed(r.actual_delta, 2, "kg"),
            f"{r.points} pts / {r.measured_days} weigh-ins",
        ]
        for r in b.rows
    ]
    return _table(["Window", "Regression", "Actual Δ (MA)", "Data"], rows)


def _forecast(b: ForecastResult) -> str:
    headers = ["Window", "Rate", *b.horizons, f"at {_d(b.goal_date)}"]
    if b.with_eta:
        headers.append("ETA goal")
    rows: list[list[str]] = []
    for r in b.rows:
        by_h = {"1m": r.m1, "3m": r.m3, "6m": r.m6}
        row = [f"{r.window} d", signed(r.kg_per_week, 2, "kg/wk")]
        row += [num(by_h.get(h), 1, "kg") for h in b.horizons]
        row.append(num(r.at_goal_date, 1, "kg"))
        if b.with_eta:
            row.append(_d(r.eta))
        rows.append(row)
    head = (
        f"Current {num(b.current_kg, 1, 'kg')} → goal {num(b.goal_kg, 1, 'kg')}"
        f" by {_d(b.goal_date)}\n\n"
    )
    return head + _table(headers, rows)


def _burndown(b: BurndownBlockResult) -> str:
    r = b.result
    ahead = "ahead of plan" if r.gap >= 0 else "behind plan"
    lines = [
        f"Anchor {_d(r.anchor)}: {num(r.remaining_at_anchor, 1, 'kg')} above goal · "
        f"today {num(r.remaining_today, 1, 'kg')} "
        f"(planned {num(r.planned_remaining_today, 1, 'kg')}, {signed(r.gap, 1, 'kg')} → {ahead})",
        f"Burned {num(r.burned, 1, 'kg')} in {r.days_elapsed} days · "
        f"actual {num(r.actual_rate_per_week, 2, 'kg/wk')} · "
        f"planned {num(r.planned_rate_per_week, 2, 'kg/wk')} · "
        f"required {num(r.required_rate_per_week, 2, 'kg/wk')}",
    ]
    if r.stages:
        rows = [
            [
                s.name,
                _d(s.date),
                num(s.required_kg_per_week, 2, "kg/wk"),
                f"{num(s.required_pct_per_week, 2)} %",
                num(s.eat_kcal_per_day, 0, "kcal"),
                "✅" if s.feasible else "⚠️",
            ]
            for s in r.stages
        ]
        lines.append("")
        lines.append(_table(["Stage", "Date", "Required", "% BW/wk", "Eat", "Feasible"], rows))
    return "\n".join(lines)


def _weekly(b: WeeklyChartResult) -> str:
    headers = ["Week"] + [{"kcal": "Ø kcal", "weight": "Ø kg", "tdee": "TDEE"}[s] for s in b.series]
    rows: list[list[str]] = []
    for w in b.rows:
        row = [_d(w.week_start)]
        for s in b.series:
            if s == "kcal":
                row.append(f"{num(w.mean_kcal, 0)} ({w.days_with_kcal} d)")
            elif s == "weight":
                row.append(num(w.mean_kg, 2))
            else:
                row.append(num(w.tdee, 0))
        rows.append(row)
    return _table(headers, rows)


def _day_list(b: DayListResult) -> str:
    headers = ["Date", *b.columns]
    rows: list[list[str]] = []
    for r in b.rows:
        row = [_d(r.date)]
        for c in b.columns:
            if c == "weight":
                row.append(num(r.weight, 1))
            elif c == "training":
                row.append(r.training_type.value if r.training_type else "–")
            elif c == "status":
                flag = "" if r.countable else " (not counted)"
                row.append(f"{r.status.value if r.status else '–'}{flag}")
            elif c == "reliable":
                row.append("yes" if r.reliable else "no" if r.reliable is False else "–")
            else:
                v = getattr(r.macros, c)
                row.append(num(v, 0 if c == "kcal" else 2 if c == "salt" else 1))
        rows.append(row)
    return _table(headers, rows)


def _block(b: BlockResult) -> str:
    title = f"### {b.meta.title}\n\n"
    if isinstance(b, BlockError):
        return title + f"⚠️ {b.message}"
    if isinstance(b, KpiTileResult):
        return _kpi(b)
    if isinstance(b, BandDistributionResult):
        return title + _band_distribution(b)
    if isinstance(b, TdeeWindowsResult):
        return title + _tdee(b)
    if isinstance(b, TrendResult):
        return title + _trend(b)
    if isinstance(b, ForecastResult):
        return title + _forecast(b)
    if isinstance(b, BurndownBlockResult):
        return title + _burndown(b)
    if isinstance(b, WeeklyChartResult):
        return title + _weekly(b)
    if isinstance(b, DayListResult):
        return title + _day_list(b)
    if isinstance(b, TextFindingResult):
        return title + (b.markdown or "_No finding recorded._")
    raise TypeError(f"unknown block result {type(b).__name__}")  # pragma: no cover


def to_markdown(result: ReportResult) -> str:
    head = [
        f"## {result.title}",
        f"_{result.period.start.isoformat()} – {result.period.end.isoformat()} "
        f"({result.period.days} days, generated "
        f"{result.generated_at.strftime('%Y-%m-%d %H:%M')} UTC)_",
    ]
    if result.description:
        head.append("")
        head.append(result.description)
    kpis = [b for b in result.blocks if isinstance(b, KpiTileResult)]
    others = [b for b in result.blocks if not isinstance(b, KpiTileResult)]
    parts = ["\n".join(head)]
    if kpis:
        parts.append("\n".join(f"- {_kpi(k)}" for k in kpis))
    parts.extend(_block(b) for b in others)
    return "\n\n".join(parts) + "\n"
