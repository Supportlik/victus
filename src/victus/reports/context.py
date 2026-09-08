"""Per-render context: the data source plus series every block may need.

Series are computed once, lazily, so ten blocks do not run the moving average
ten times. Only *countable* days (``reliable`` and ``closed``) feed the calorie
and macro series — the same rule as the predecessor's ``tag_zaehlbar`` view.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cached_property

from victus.application.ports.report_data import DayMacros, ReportDataSource, TenantReportSettings
from victus.domain.model.reporting import RollingRow, WeekRow
from victus.domain.services import tdee, trend
from victus.domain.values import Period


class ReportContext:
    def __init__(self, source: ReportDataSource, period: Period, today: date) -> None:
        self.source = source
        self.period = period
        self.today = today

    # ── settings and raw series ──────────────────────────────────────────

    @cached_property
    def settings(self) -> TenantReportSettings:
        return self.source.settings()

    @cached_property
    def weights(self) -> dict[date, float]:
        """All weigh-ins up to ``today`` (later ones would leak the future)."""
        return {d: v for d, v in self.source.all_weights().items() if d <= self.today}

    @cached_property
    def ma(self) -> dict[date, float]:
        return trend.moving_average(self.weights, self.settings.moving_average_days)

    @cached_property
    def all_days(self) -> dict[date, DayMacros]:
        return {d: v for d, v in self.source.all_day_macros().items() if d <= self.today}

    @cached_property
    def period_days(self) -> dict[date, DayMacros]:
        return {d: v for d, v in self.all_days.items() if self.period.start <= d <= self.period.end}

    def _series(self, macro: str, days: dict[date, DayMacros]) -> dict[date, float]:
        out: dict[date, float] = {}
        for d, dm in days.items():
            if not dm.countable:
                continue
            v = getattr(dm.macros, macro)
            if v is not None:
                out[d] = float(v)
        return out

    @cached_property
    def calories(self) -> dict[date, float]:
        """kcal of every countable day in history."""
        return self._series("kcal", self.all_days)

    @cached_property
    def protein(self) -> dict[date, float]:
        return self._series("protein", self.all_days)

    def macro_series(self, macro: str, within_period: bool = True) -> dict[date, float]:
        return self._series(macro, self.period_days if within_period else self.all_days)

    # ── derived values ───────────────────────────────────────────────────

    @cached_property
    def current_kg(self) -> float | None:
        """Moving average on ``today`` or the last MA value before it."""
        if not self.ma:
            return None
        if self.today in self.ma:
            return self.ma[self.today]
        earlier = [d for d in self.ma if d <= self.today]
        return self.ma[max(earlier)] if earlier else None

    @cached_property
    def latest_weight(self) -> tuple[date, float] | None:
        if not self.weights:
            return None
        d = max(self.weights)
        return d, self.weights[d]

    def ma_at_or_before(self, day: date) -> float | None:
        cands = [d for d in self.ma if d <= day]
        return self.ma[max(cands)] if cands else None

    @cached_property
    def ma_end(self) -> date | None:
        """Last MA date at or before ``today`` — the end of rolling windows."""
        cands = [d for d in self.ma if d <= self.today]
        return max(cands) if cands else None

    @cached_property
    def rolling(self) -> list[RollingRow]:
        if self.ma_end is None:
            return []
        return tdee.rolling_tdee(
            self.weights,
            self.ma,
            self.calories,
            self.protein,
            self.settings.tdee_windows,
            self.settings.kcal_per_kg,
            self.settings.corridor,
            end=self.ma_end,
        )

    def rolling_for(self, windows: list[int] | None) -> list[RollingRow]:
        if windows is None:
            return self.rolling
        known = {r.window_days: r for r in self.rolling}
        rows: list[RollingRow] = []
        for w in windows:
            if w in known:
                rows.append(known[w])
            elif self.ma_end is not None:
                row = tdee.rolling_window(
                    self.weights,
                    self.ma,
                    self.calories,
                    self.protein,
                    w,
                    self.settings.kcal_per_kg,
                    self.settings.corridor,
                    end=self.ma_end,
                )
                if row is not None:
                    rows.append(row)
        return rows

    @cached_property
    def weekly(self) -> list[WeekRow]:
        return tdee.weekly_tdee(self.weights, self.calories, self.settings.kcal_per_kg)

    @cached_property
    def reference_tdee(self) -> tuple[int | None, str]:
        return tdee.reference_tdee(self.weekly, self.rolling)

    def previous_period(self) -> Period:
        length = self.period.days
        return Period(
            start=self.period.start - timedelta(days=length),
            end=self.period.start - timedelta(days=1),
        )
