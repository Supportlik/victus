"""``ReportDataSource`` backed by the tenant-scoped repositories of a unit of work.

The adapter reads only: day totals from the ``day_macros`` view via ``DayLogRepo``,
daily mean weights, target bands, the current tenant settings and the newest agent
summary. Conversions from ORM rows to domain value objects live here so the report
engine and the API never see SQLAlchemy objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from victus.application.ports.report_data import DayMacros, TenantReportSettings
from victus.domain.model.reporting import Stage
from victus.domain.values import (
    Band,
    CalorieCorridor,
    DayStatus,
    Macros,
    Period,
    TargetBand,
    TrainingType,
)
from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

_MACROS = ("protein", "carbs", "fat", "fiber", "salt")


def band_from_orm(row: orm.TargetBand) -> TargetBand:
    """Convert a ``target_band`` row into the domain ``TargetBand``."""

    def band(prefix: str, *, stretch: bool) -> Band:
        return Band(
            min=float(getattr(row, f"{prefix}_min") or 0.0),
            opt_min=float(getattr(row, f"{prefix}_opt_min") or 0.0),
            opt_max=float(getattr(row, f"{prefix}_opt_max") or 0.0),
            target=float(getattr(row, f"{prefix}_target") or 0.0),
            max=float(getattr(row, f"{prefix}_max") or 0.0),
            stretch=getattr(row, f"{prefix}_stretch", None) if stretch else None,
        )

    kcal = None
    if row.kcal_min is not None or row.kcal_max is not None:
        kcal = band("kcal", stretch=False)
    return TargetBand(
        name=row.name,
        training_type=TrainingType(row.training_type) if row.training_type else None,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        protein=band("protein", stretch=True),
        carbs=band("carbs", stretch=False),
        fat=band("fat", stretch=False),
        fiber=band("fiber", stretch=True),
        salt=band("salt", stretch=False),
        kcal=kcal,
    )


def active_goal(data: Mapping[str, Any]) -> Mapping[str, Any]:
    """The goal the reports run on.

    A tenant may keep several goals; the active one wins, otherwise the first
    entry, otherwise the single legacy ``goal`` object.
    """
    goals = data.get("goals")
    if isinstance(goals, list) and goals:
        chosen = next((g for g in goals if isinstance(g, dict) and g.get("active")), None)
        first = next((g for g in goals if isinstance(g, dict)), None)
        picked = chosen or first
        if picked is not None:
            return picked
    single = data.get("goal")
    return single if isinstance(single, dict) else {}


def settings_from_data(data: Mapping[str, Any]) -> TenantReportSettings:
    """Build the engine's settings subset from the tenant settings document."""
    goal = active_goal(data)
    corridor = data.get("calorie_corridor") or {}
    stages = [
        Stage(name=str(s["name"]), date=date.fromisoformat(str(s["date"])))
        for s in goal.get("stages", [])
        if "name" in s and "date" in s
    ]
    burndown = data.get("burndown_start")
    return TenantReportSettings(
        goal_kg=float(goal.get("weight_kg", 0.0)),
        goal_date=date.fromisoformat(str(goal.get("date", date.today().isoformat()))),
        kcal_per_kg=float(data.get("kcal_per_kg", 7716.17)),
        moving_average_days=int(data.get("moving_average_days", 7)),
        trend_windows=tuple(int(w) for w in data.get("trend_windows", (7, 14, 21, 30, 60, 90))),
        tdee_windows=tuple(int(w) for w in data.get("tdee_windows", (3, 7, 14, 21, 30, 60, 90))),
        corridor=CalorieCorridor(
            min=int(corridor.get("min", 1400)),
            max=int(corridor.get("max", 2000)),
            asymmetric=bool(corridor.get("asymmetric", True)),
        ),
        stages=tuple(stages),
        burndown_start=date.fromisoformat(str(burndown)) if burndown else None,
        goal_name=str(goal["name"]) if goal.get("name") else None,
    )


class SqlAlchemyReportDataSource:
    """Implements ``ReportDataSource`` on top of an open unit of work."""

    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    # ── weights ──────────────────────────────────────────────────────────

    def weights(self, period: Period) -> Mapping[date, float]:
        return self._uow.weights.daily_means(period.start, period.end)

    def all_weights(self) -> Mapping[date, float]:
        return self._uow.weights.daily_means()

    # ── day totals ───────────────────────────────────────────────────────

    def day_macros(self, period: Period) -> Mapping[date, DayMacros]:
        return self._days(period.start, period.end)

    def all_day_macros(self) -> Mapping[date, DayMacros]:
        return self._days(None, None)

    def _days(self, start: date | None, end: date | None) -> dict[date, DayMacros]:
        logs = self._uow.day_logs.list(start, end)
        if not logs:
            return {}
        first = start or logs[0].date
        last = end or logs[-1].date
        totals = self._uow.day_logs.macros_between(first, last)
        countable = set(self._uow.day_logs.countable_days(first, last))
        out: dict[date, DayMacros] = {}
        for log in logs:
            macros = totals.get(log.date)
            if macros is None:
                # No line items: fall back to the imported source totals, if any.
                macros = Macros(
                    kcal=log.source_kcal,
                    protein=log.source_protein,
                    carbs=log.source_carbs,
                    fat=log.source_fat,
                    fiber=log.source_fiber,
                    salt=log.source_salt,
                )
            out[log.date] = DayMacros(
                date=log.date,
                macros=macros,
                status=DayStatus(log.status) if log.status else None,
                reliable=log.reliable,
                training_type=TrainingType(log.training_type) if log.training_type else None,
                countable=log.date in countable or self._counts_by_flags(log, macros),
            )
        return out

    @staticmethod
    def _counts_by_flags(log: orm.DayLog, macros: Macros) -> bool:
        """Imported days without line items count when their flags say so."""
        return bool(log.reliable) and log.status == DayStatus.CLOSED and macros.kcal is not None

    # ── bands, settings, findings ────────────────────────────────────────

    def target_band_for(self, day: date, training_type: TrainingType | None) -> TargetBand | None:
        row = self._uow.target_bands.for_date(day, training_type)
        return band_from_orm(row) if row else None

    def settings(self) -> TenantReportSettings:
        current = self._uow.settings.current()
        return settings_from_data(current.data if current else {})

    def latest_finding(self, source: str) -> str | None:
        if source != "agent":
            return None
        for run in self._uow.agent.list_runs(limit=20):
            if run.summary_md:
                return run.summary_md
        return None


__all__ = ["SqlAlchemyReportDataSource", "active_goal", "band_from_orm", "settings_from_data"]
