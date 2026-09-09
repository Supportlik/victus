"""Weight entries: the scale sync owns the series; people may only add manual rows."""

from __future__ import annotations

from datetime import date, datetime

from victus.application import dto
from victus.application.errors import Conflict, Forbidden, NotFound, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase
from victus.application.use_cases.settings import regional_of
from victus.domain.values import WeightSource
from victus.infrastructure.db import orm


def _view(e: orm.WeightEntry) -> dto.WeightEntryView:
    return dto.WeightEntryView(id=e.id, measured_at=e.measured_at, kg=e.kg, source=e.source)


class ListWeights(UseCase):
    def execute(
        self, start: date | None = None, end: date | None = None
    ) -> list[dto.WeightEntryView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [_view(e) for e in uow.weights.list(start, end)]


class DailyMeans(UseCase):
    def execute(self, start: date | None = None, end: date | None = None) -> dict[date, float]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return uow.weights.daily_means(start, end, regional_of(uow).timezone)


class AddManualWeight(UseCase):
    def execute(
        self, measured_at: datetime, kg: float, *, source: str = "manual"
    ) -> dto.WeightEntryView:
        self.ctx.require(SCOPE_WRITE)
        if source != WeightSource.MANUAL.value:
            raise Forbidden("only manual weight entries can be added through the app")
        if not 20 <= kg <= 400:
            raise ValidationFailed("kg out of plausible range")
        with self._uow() as uow:
            if uow.weights.by_measured_at(measured_at) is not None:
                raise Conflict("an entry with this timestamp exists")
            e = uow.weights.add(
                orm.WeightEntry(
                    tenant_id=self.ctx.tenant_id, measured_at=measured_at, kg=kg, source=source
                )
            )
            uow.audit.record("weight.add", "weight_entry", str(e.id), {"kg": kg})
            view = _view(e)
            uow.commit()
            return view


class DeleteManualWeight(UseCase):
    def execute(self, entry_id: int) -> None:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            e = uow.weights.get(entry_id)
            if e is None:
                raise NotFound(f"weight entry {entry_id} not found")
            if e.source != WeightSource.MANUAL.value:
                raise Forbidden("only manual entries can be deleted")
            uow.audit.record("weight.delete", "weight_entry", str(e.id), {"kg": e.kg})
            uow.weights.delete(e)
            uow.commit()
