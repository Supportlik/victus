"""An in-memory :class:`ReportDataSource` — for tests and for rendering from files
(vault export) without a database."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from victus.application.ports.report_data import DayMacros, TenantReportSettings
from victus.domain.services import target_band as tb
from victus.domain.values import Period, TargetBand, TrainingType


class InMemoryReportDataSource:
    def __init__(
        self,
        *,
        weights: Mapping[date, float],
        days: Mapping[date, DayMacros],
        settings: TenantReportSettings,
        bands: Sequence[TargetBand] = (),
        findings: Mapping[str, str] | None = None,
    ) -> None:
        self._weights = dict(weights)
        self._days = dict(days)
        self._settings = settings
        self._bands = list(bands)
        self._findings = dict(findings or {})

    def weights(self, period: Period) -> Mapping[date, float]:
        return {d: v for d, v in self._weights.items() if period.start <= d <= period.end}

    def all_weights(self) -> Mapping[date, float]:
        return self._weights

    def day_macros(self, period: Period) -> Mapping[date, DayMacros]:
        return {d: v for d, v in self._days.items() if period.start <= d <= period.end}

    def all_day_macros(self) -> Mapping[date, DayMacros]:
        return self._days

    def target_band_for(self, day: date, training_type: TrainingType | None) -> TargetBand | None:
        return tb.select_band(self._bands, day, training_type)

    def settings(self) -> TenantReportSettings:
        return self._settings

    def latest_finding(self, source: str) -> str | None:
        return self._findings.get(source)
