"""Day logs, meals, line items, weights, target bands and tenant settings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from victus.domain.services.calendar import day_of
from victus.domain.values import Macros, TrainingType
from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


def _macros(row: Any) -> Macros:
    return Macros(
        kcal=row.kcal,
        protein=row.protein,
        carbs=row.carbs,
        fat=row.fat,
        fiber=row.fiber,
        salt=row.salt,
    )


class DayLogRepo(Repo):
    def get(self, day_log_id: int) -> orm.DayLog | None:
        return self.session.scalar(
            self.scoped(select(orm.DayLog).where(orm.DayLog.id == day_log_id), orm.DayLog)
        )

    def get_by_date(self, day: date) -> orm.DayLog | None:
        return self.session.scalar(
            self.scoped(select(orm.DayLog).where(orm.DayLog.date == day), orm.DayLog)
        )

    def add(self, day_log: orm.DayLog) -> orm.DayLog:
        self.guard(day_log)
        self.session.add(day_log)
        self.session.flush()
        return day_log

    def list(
        self,
        start: date | None = None,
        end: date | None = None,
        status: str | None = None,
    ) -> Sequence[orm.DayLog]:
        stmt = self.scoped(select(orm.DayLog), orm.DayLog)
        if start:
            stmt = stmt.where(orm.DayLog.date >= start)
        if end:
            stmt = stmt.where(orm.DayLog.date <= end)
        if status:
            stmt = stmt.where(orm.DayLog.status == status)
        return self.session.scalars(stmt.order_by(orm.DayLog.date)).all()

    def draft_days(self) -> Sequence[orm.DayLog]:
        draft_item_days = (
            select(orm.Meal.day_log_id)
            .join(orm.LineItem, orm.LineItem.meal_id == orm.Meal.id)
            .where(orm.LineItem.is_draft.is_(True))
        )
        stmt = self.scoped(
            select(orm.DayLog).where(
                (orm.DayLog.status == "draft") | orm.DayLog.id.in_(draft_item_days)
            ),
            orm.DayLog,
        )
        return self.session.scalars(stmt.order_by(orm.DayLog.date)).all()

    def delete_day(self, day_log: orm.DayLog) -> None:
        self.guard(day_log)
        self.session.delete(day_log)
        self.session.flush()

    # ── computed macros (views) ──
    def macros_for(self, day: date) -> Macros | None:
        row = (
            self.session.execute(
                text("SELECT * FROM day_macros WHERE tenant_id = :t AND date = :d"),
                {"t": self.tenant_id, "d": day},
            )
            .mappings()
            .first()
        )
        if row is None or row["item_count"] == 0:
            return None
        return _macros(_Row(row))

    def macros_between(self, start: date, end: date) -> dict[date, Macros]:
        rows = self.session.execute(
            text(
                "SELECT * FROM day_macros WHERE tenant_id = :t AND date >= :s AND date <= :e "
                "AND item_count > 0 ORDER BY date"
            ),
            {"t": self.tenant_id, "s": start, "e": end},
        ).mappings()
        return {_as_date(r["date"]): _macros(_Row(r)) for r in rows}

    def countable_days(self, start: date | None = None, end: date | None = None) -> Sequence[date]:
        sql = "SELECT date FROM countable_days WHERE tenant_id = :t"
        params: dict[str, Any] = {"t": self.tenant_id}
        if start:
            sql += " AND date >= :s"
            params["s"] = start
        if end:
            sql += " AND date <= :e"
            params["e"] = end
        return [
            _as_date(r[0]) for r in self.session.execute(text(sql + " ORDER BY date"), params).all()
        ]

    def line_item_macros(self, day: date) -> dict[int, Macros]:
        rows = self.session.execute(
            text(
                "SELECT lm.* FROM line_item_macros lm JOIN day_log d ON d.id = lm.day_log_id "
                "WHERE d.tenant_id = :t AND d.date = :d"
            ),
            {"t": self.tenant_id, "d": day},
        ).mappings()
        return {int(r["id"]): _macros(_Row(r)) for r in rows}

    def usage_of(self, consumable_id: int, limit: int = 100) -> Sequence[Mapping[str, Any]]:
        """Where a consumable was logged: newest day first, with its computed macros."""
        rows = self.session.execute(
            text(
                "SELECT d.date AS date, d.status AS day_status, m.name AS meal, "
                "       lm.id AS line_item_id, lm.amount, lm.unit_code, lm.base_amount, "
                "       lm.base_unit, lm.is_draft, lm.estimated, lm.amount_estimated, "
                "       lm.kcal, lm.protein, lm.carbs, lm.fat, lm.fiber, lm.salt "
                "  FROM line_item_macros lm "
                "  JOIN meal m ON m.id = lm.meal_id "
                "  JOIN day_log d ON d.id = m.day_log_id "
                " WHERE d.tenant_id = :t AND lm.id IN ("
                "       SELECT li.id FROM line_item li WHERE li.consumable_id = :c) "
                " ORDER BY d.date DESC, m.position, lm.position "
                " LIMIT :n"
            ),
            {"t": self.tenant_id, "c": consumable_id, "n": limit},
        ).mappings()
        return [dict(r) for r in rows]

    # ── meals / items ──
    def add_meal(self, meal: orm.Meal) -> orm.Meal:
        if self.get(meal.day_log_id) is None:
            raise PermissionError("day log not in tenant")
        self.session.add(meal)
        self.session.flush()
        return meal

    def get_meal(self, meal_id: int) -> orm.Meal | None:
        stmt = (
            select(orm.Meal)
            .join(orm.DayLog, orm.DayLog.id == orm.Meal.day_log_id)
            .where(orm.Meal.id == meal_id, orm.DayLog.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)

    def delete_meal(self, meal: orm.Meal) -> None:
        if self.get(meal.day_log_id) is None:
            raise PermissionError("day log not in tenant")
        self.session.delete(meal)
        self.session.flush()

    def add_line_item(self, item: orm.LineItem) -> orm.LineItem:
        if self.get_meal(item.meal_id) is None:
            raise PermissionError("meal not in tenant")
        self.session.add(item)
        self.session.flush()
        return item

    def get_line_item(self, item_id: int) -> orm.LineItem | None:
        stmt = (
            select(orm.LineItem)
            .join(orm.Meal, orm.Meal.id == orm.LineItem.meal_id)
            .join(orm.DayLog, orm.DayLog.id == orm.Meal.day_log_id)
            .where(orm.LineItem.id == item_id, orm.DayLog.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)

    def delete_line_item(self, item: orm.LineItem) -> None:
        if self.get_line_item(item.id) is None:
            raise PermissionError("line item not in tenant")
        self.session.delete(item)
        self.session.flush()


class _Row:
    """Attribute access over a RowMapping (keeps ``_macros`` simple)."""

    def __init__(self, mapping: Any) -> None:
        self._m = mapping

    def __getattr__(self, name: str) -> Any:
        return self._m[name]


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class WeightRepo(Repo):
    def add(self, entry: orm.WeightEntry) -> orm.WeightEntry:
        self.guard(entry)
        self.session.add(entry)
        self.session.flush()
        return entry

    def get(self, entry_id: int) -> orm.WeightEntry | None:
        return self.session.scalar(
            self.scoped(
                select(orm.WeightEntry).where(orm.WeightEntry.id == entry_id), orm.WeightEntry
            )
        )

    def list(self, start: date | None = None, end: date | None = None) -> Sequence[orm.WeightEntry]:
        stmt = self.scoped(select(orm.WeightEntry), orm.WeightEntry)
        if start:
            stmt = stmt.where(func.date(orm.WeightEntry.measured_at) >= start)
        if end:
            stmt = stmt.where(func.date(orm.WeightEntry.measured_at) <= end)
        return self.session.scalars(stmt.order_by(orm.WeightEntry.measured_at)).all()

    def by_measured_at(self, measured_at: datetime) -> orm.WeightEntry | None:
        return self.session.scalar(
            self.scoped(
                select(orm.WeightEntry).where(orm.WeightEntry.measured_at == measured_at),
                orm.WeightEntry,
            )
        )

    def delete(self, entry: orm.WeightEntry) -> None:
        self.guard(entry)
        self.session.delete(entry)
        self.session.flush()

    def daily_means(
        self, start: date | None = None, end: date | None = None, tz: str | None = None
    ) -> dict[date, float]:
        """One value per day (mean of that day's measurements), computed in Python.

        A weigh-in just after midnight is the previous day in UTC, so the day is taken
        in ``tz`` (R69). The range is widened by a day on both sides, because a local
        day reaches into the neighbouring UTC ones.
        """
        widened_start = start - timedelta(days=1) if start else None
        widened_end = end + timedelta(days=1) if end else None
        sums: dict[date, list[float]] = {}
        for e in self.list(widened_start, widened_end):
            day = day_of(e.measured_at, tz)
            if (start and day < start) or (end and day > end):
                continue
            sums.setdefault(day, []).append(e.kg)
        return {d: sum(v) / len(v) for d, v in sorted(sums.items())}


class TargetBandRepo(Repo):
    def get(self, band_id: int) -> orm.TargetBand | None:
        return self.session.scalar(
            self.scoped(select(orm.TargetBand).where(orm.TargetBand.id == band_id), orm.TargetBand)
        )

    def add(self, band: orm.TargetBand) -> orm.TargetBand:
        self.guard(band)
        self.session.add(band)
        self.session.flush()
        return band

    def list(self) -> Sequence[orm.TargetBand]:
        return self.session.scalars(
            self.scoped(select(orm.TargetBand), orm.TargetBand).order_by(
                orm.TargetBand.valid_from, orm.TargetBand.training_type
            )
        ).all()

    def for_date(self, day: date, training_type: TrainingType | None) -> orm.TargetBand | None:
        """Most specific band valid on ``day``: matching training type first, then generic."""
        tt = training_type.value if training_type else None
        stmt = self.scoped(
            select(orm.TargetBand).where(
                orm.TargetBand.valid_from <= day,
                (orm.TargetBand.valid_until.is_(None)) | (orm.TargetBand.valid_until >= day),
                (orm.TargetBand.training_type == tt) | (orm.TargetBand.training_type.is_(None)),
            ),
            orm.TargetBand,
        )
        candidates = self.session.scalars(stmt).all()
        if not candidates:
            return None
        candidates = sorted(
            candidates, key=lambda b: (b.training_type is None, -b.valid_from.toordinal())
        )
        return candidates[0]


class SettingsRepo(Repo):
    def current(self) -> orm.TenantSettings | None:
        return self.session.scalar(
            self.scoped(select(orm.TenantSettings), orm.TenantSettings)
            .order_by(orm.TenantSettings.version.desc())
            .limit(1)
        )

    def for_date(self, day: date) -> orm.TenantSettings | None:
        return self.session.scalar(
            self.scoped(
                select(orm.TenantSettings).where(orm.TenantSettings.valid_from <= day),
                orm.TenantSettings,
            )
            .order_by(orm.TenantSettings.valid_from.desc(), orm.TenantSettings.version.desc())
            .limit(1)
        )

    def versions(self) -> Sequence[orm.TenantSettings]:
        return self.session.scalars(
            self.scoped(select(orm.TenantSettings), orm.TenantSettings).order_by(
                orm.TenantSettings.version
            )
        ).all()

    def add_version(
        self, data: dict[str, Any], valid_from: date, changed_by: str | None
    ) -> orm.TenantSettings:
        latest = self.current()
        version = 1 if latest is None else latest.version + 1
        row = orm.TenantSettings(
            tenant_id=self.tenant_id,
            version=version,
            valid_from=valid_from,
            data=data,
            changed_by=changed_by,
        )
        self.session.add(row)
        self.session.flush()
        return row
