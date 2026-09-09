"""Body measurements: tape-measure sessions and the figures derived from them (R76)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase
from victus.domain.services import body as calc
from victus.infrastructure.db import orm

#: Circumferences, in the order a report shows them.
CIRCUMFERENCES = ("waist_cm", "belly_cm", "hip_cm", "chest_cm", "neck_cm", "thigh_cm", "arm_cm")

#: A tape measure around a human torso; outside this the entry is a typo.
PLAUSIBLE_CM = (10.0, 250.0)


@dataclass(frozen=True, slots=True)
class BodyInput:
    """One session. Everything but the timestamp is optional."""

    measured_at: dt.datetime
    waist_cm: float | None = None
    belly_cm: float | None = None
    hip_cm: float | None = None
    chest_cm: float | None = None
    neck_cm: float | None = None
    thigh_cm: float | None = None
    arm_cm: float | None = None
    body_fat_pct: float | None = None
    note: str | None = None

    def values(self) -> dict[str, float | None]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name in CIRCUMFERENCES}


def _view(row: orm.BodyMeasurement) -> dto.BodyMeasurementView:
    return dto.BodyMeasurementView(
        id=row.id,
        measured_at=row.measured_at,
        waist_cm=row.waist_cm,
        belly_cm=row.belly_cm,
        hip_cm=row.hip_cm,
        chest_cm=row.chest_cm,
        neck_cm=row.neck_cm,
        thigh_cm=row.thigh_cm,
        arm_cm=row.arm_cm,
        body_fat_pct=row.body_fat_pct,
        note=row.note,
        source=row.source,
    )


def body_profile(uow: UnitOfWork) -> tuple[float | None, calc.Sex | None, dt.date | None]:
    """(height_cm, sex, birth_date) from the tenant's settings; any of them may be missing.

    Nothing here is required to run Victus, so every consumer has to cope with None. A
    report that cannot compute a figure says which field is missing rather than guessing.
    """
    current = uow.settings.current()
    data: dict[str, Any] = dict(current.data) if current is not None else {}
    section = data.get("body")
    if not isinstance(section, dict):
        return None, None, None
    raw_height = section.get("height_cm")
    height = float(raw_height) if isinstance(raw_height, int | float) else None
    sex: calc.Sex | None = None
    raw_sex = section.get("sex")
    if isinstance(raw_sex, str):
        try:
            sex = calc.Sex(raw_sex)
        except ValueError:
            sex = None
    birth: dt.date | None = None
    raw_birth = section.get("birth_date")
    if isinstance(raw_birth, str):
        try:
            birth = dt.date.fromisoformat(raw_birth)
        except ValueError:
            birth = None
    return height, sex, birth


class ListBodyMeasurements(UseCase):
    def execute(
        self,
        start: dt.date | None = None,
        end: dt.date | None = None,
        limit: int | None = None,
    ) -> list[dto.BodyMeasurementView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [_view(r) for r in uow.body.list(start, end, limit)]


class AddBodyMeasurement(UseCase):
    def execute(self, data: BodyInput) -> dto.BodyMeasurementView:
        self.ctx.require(SCOPE_WRITE)
        given = {k: v for k, v in data.values().items() if v is not None}
        if not given and data.body_fat_pct is None:
            raise ValidationFailed("a measurement needs at least one value")
        low, high = PLAUSIBLE_CM
        for name, value in given.items():
            if not low <= value <= high:
                raise ValidationFailed(f"{name} out of plausible range ({low:g}–{high:g} cm)")
        if data.body_fat_pct is not None and not 3 <= data.body_fat_pct <= 70:
            raise ValidationFailed("body fat percentage out of plausible range (3–70)")
        with self._uow() as uow:
            if uow.body.by_measured_at(data.measured_at) is not None:
                raise Conflict("a measurement with this timestamp exists")
            row = uow.body.add(
                orm.BodyMeasurement(
                    tenant_id=self.ctx.tenant_id,
                    measured_at=data.measured_at,
                    body_fat_pct=data.body_fat_pct,
                    note=data.note,
                    source="manual",
                    **given,
                )
            )
            uow.audit.record("body.add", "body_measurement", str(row.id), {"fields": [*given]})
            view = _view(row)
            uow.commit()
            return view


class DeleteBodyMeasurement(UseCase):
    def execute(self, row_id: int) -> None:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            row = uow.body.get(row_id)
            if row is None:
                raise NotFound(f"body measurement {row_id} not found")
            uow.audit.record("body.delete", "body_measurement", str(row.id), {})
            uow.body.delete(row)
            uow.commit()
