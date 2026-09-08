"""Day logs: list, detail, meals, line items, flags, close/reopen, day thread."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase, now
from victus.application.use_cases._mappers import (
    line_item_view,
    target_band_domain,
    target_band_view,
    weekday_name,
)
from victus.application.use_cases.captures import queue_follow_up_if_needed
from victus.domain.model.checks import DayForCheck
from victus.domain.services.nutrients import sum_macros
from victus.domain.services.units import UNITS, base_factor
from victus.domain.services.validation import check_day
from victus.domain.values import (
    MACRO_KEYS,
    BandZone,
    CaptureKind,
    CaptureStatus,
    DayStatus,
    Macros,
    MessageKind,
    MessageRole,
    TrainingType,
)
from victus.infrastructure.db import orm


@dataclass(frozen=True, slots=True)
class LineItemInput:
    consumable_id: int
    amount: float
    unit_code: str
    portion_id: int | None = None
    estimated: bool = False
    amount_estimated: bool = False
    raw_text: str | None = None


def _training(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        return TrainingType(value).value
    except ValueError as exc:
        raise ValidationFailed(f"unknown training_type '{value}'") from exc


def resolve_base(
    uow: UnitOfWork, consumable: orm.Consumable, item: LineItemInput
) -> tuple[float, str, int | None]:
    """Turn (amount, unit, portion) into the frozen base amount in g/ml."""
    if item.amount is None or item.amount < 0:
        raise ValidationFailed("amount must be zero or positive")
    spec = UNITS.get(item.unit_code)
    if spec is None:
        raise ValidationFailed(f"unknown unit '{item.unit_code}'")
    factor = base_factor(item.unit_code)
    if factor is not None:
        return item.amount * factor[0], factor[1], None
    # count unit → needs a portion of the product
    if consumable.kind != "product":
        raise ValidationFailed("count units need a product portion")
    portions = list(uow.products.portions_for(consumable.id))
    chosen: orm.Portion | None = None
    if item.portion_id is not None:
        chosen = next((p for p in portions if p.id == item.portion_id), None)
        if chosen is None:
            raise NotFound(f"portion {item.portion_id} not found")
    else:
        same_unit = [p for p in portions if p.unit_code == item.unit_code]
        chosen = next((p for p in same_unit if p.is_default), same_unit[0] if same_unit else None)
    if chosen is None:
        raise ValidationFailed(
            f"no portion for unit '{item.unit_code}'; give a portion or a weight"
        )
    return item.amount * chosen.amount, chosen.amount_unit, chosen.id


def _day_or_404(uow: UnitOfWork, day: date) -> orm.DayLog:
    d = uow.day_logs.get_by_date(day)
    if d is None:
        raise NotFound(f"no day log for {day.isoformat()}")
    return d


def build_day_view(uow: UnitOfWork, d: orm.DayLog) -> dto.DayView:
    item_macros = uow.day_logs.line_item_macros(d.date)
    meals: list[dto.MealView] = []
    has_drafts = d.status == DayStatus.DRAFT.value
    for meal in d.meals:
        items = []
        for li in meal.line_items:
            m = item_macros.get(li.id)
            items.append(line_item_view(li, m, li.consumable))
            has_drafts = has_drafts or bool(li.is_draft)
        totals = sum_macros(item_macros[li.id] for li in meal.line_items if li.id in item_macros)
        meals.append(
            dto.MealView(meal.id, meal.position, meal.name or "", meal.time, items, totals)
        )
    macros = uow.day_logs.macros_for(d.date) or Macros()
    band_row = (
        uow.target_bands.get(d.target_band_id)
        if d.target_band_id
        else uow.target_bands.for_date(
            d.date, TrainingType(d.training_type) if d.training_type else None
        )
    )
    band_view = target_band_view(band_row) if band_row else None
    zones: dict[str, BandZone] = {}
    if band_row is not None:
        band = target_band_domain(band_row)
        if band is not None:
            for key in MACRO_KEYS:
                b = band.band_for(key)
                v = getattr(macros, key)
                if b is not None and v is not None:
                    zones[key] = b.zone(v)
    source = Macros(
        kcal=d.source_kcal,
        protein=d.source_protein,
        carbs=d.source_carbs,
        fat=d.source_fat,
        fiber=d.source_fiber,
        salt=d.source_salt,
    )
    has_source = any(getattr(source, k) is not None for k in MACRO_KEYS)
    findings = check_day(
        DayForCheck(
            day=d.date,
            reliable=d.reliable,
            status=DayStatus(d.status),
            source=source if has_source else None,
            balance=macros if has_source else None,
            meal_totals=[m.totals for m in meals],
            item_sum=macros,
        )
    )
    weights = uow.weights.daily_means(d.date, d.date)
    return dto.DayView(
        date=d.date,
        status=d.status,
        reliable=d.reliable,
        training_type=d.training_type,
        macros=macros,
        has_drafts=has_drafts,
        weight_kg=weights.get(d.date),
        weekday=d.weekday or weekday_name(d.date),
        meals=meals,
        target_band=band_view,
        zones=zones,
        findings=findings,
        notes=d.training_note,
    )


class ListDays(UseCase):
    def execute(
        self, start: date, end: date, status: str | None = None
    ) -> list[dto.DaySummaryView]:
        self.ctx.require(SCOPE_READ)
        if end < start:
            raise ValidationFailed("to must not be before from")
        with self._uow() as uow:
            macros = uow.day_logs.macros_between(start, end)
            weights = uow.weights.daily_means(start, end)
            draft_days = {d.date for d in uow.day_logs.draft_days()}
            out = []
            for d in uow.day_logs.list(start, end, status):
                out.append(
                    dto.DaySummaryView(
                        date=d.date,
                        status=d.status,
                        reliable=d.reliable,
                        training_type=d.training_type,
                        macros=macros.get(d.date, Macros()),
                        has_drafts=d.date in draft_days,
                        weight_kg=weights.get(d.date),
                    )
                )
            return out


class GetDay(UseCase):
    def execute(self, day: date) -> dto.DayView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return build_day_view(uow, _day_or_404(uow, day))


class CreateDay(UseCase):
    def execute(
        self,
        day: date,
        *,
        reliable: bool,
        training_type: str | None = None,
        notes: str | None = None,
    ) -> dto.DayView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            if uow.day_logs.get_by_date(day) is not None:
                raise Conflict(f"day log for {day.isoformat()} exists")
            d = uow.day_logs.add(
                orm.DayLog(
                    tenant_id=self.ctx.tenant_id,
                    date=day,
                    weekday=weekday_name(day),
                    reliable=reliable,
                    status=DayStatus.OPEN.value,
                    training_type=_training(training_type),
                    training_note=notes,
                    created_by_kind="user",
                )
            )
            uow.audit.record("day.create", "day_log", str(d.id), {"date": day.isoformat()})
            view = build_day_view(uow, d)
            uow.commit()
            return view


class UpdateDayFlags(UseCase):
    def execute(self, day: date, changes: dict[str, Any]) -> dto.DayView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            d = _day_or_404(uow, day)
            diff: dict[str, Any] = {}
            if "reliable" in changes:
                d.reliable = changes["reliable"]
                diff["reliable"] = changes["reliable"]
            if "training_type" in changes:
                d.training_type = _training(changes["training_type"])
                diff["training_type"] = d.training_type
            if "notes" in changes:
                d.training_note = changes["notes"]
                diff["notes"] = changes["notes"]
            uow.audit.record("day.update", "day_log", str(d.id), diff)
            uow.flush()
            view = build_day_view(uow, d)
            uow.commit()
            return view


class AddMeal(UseCase):
    def execute(self, day: date, name: str, at: dt.time | None = None) -> dto.MealView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            d = _day_or_404(uow, day)
            position = (max((m.position for m in d.meals), default=0)) + 1
            meal = uow.day_logs.add_meal(
                orm.Meal(day_log_id=d.id, position=position, name=name, time=at)
            )
            view = dto.MealView(meal.id, meal.position, meal.name or "", meal.time, [], Macros())
            uow.commit()
            return view


class UpdateMeal(UseCase):
    """Rename a meal or change its time."""

    def execute(self, meal_id: int, changes: dict[str, Any]) -> dto.MealView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            meal = uow.day_logs.get_meal(meal_id)
            if meal is None:
                raise NotFound(f"meal {meal_id} not found")
            diff: dict[str, Any] = {}
            if changes.get("name") is not None:
                name = str(changes["name"]).strip()
                if not name:
                    raise ValidationFailed("meal name must not be empty")
                diff["name"] = [meal.name, name]
                meal.name = name
            if "time" in changes:
                diff["time"] = [
                    meal.time.isoformat() if meal.time else None,
                    changes["time"].isoformat() if changes["time"] else None,
                ]
                meal.time = changes["time"]
            uow.audit.record("meal.update", "meal", str(meal.id), diff)
            uow.flush()
            view = build_day_view(uow, meal.day_log)
            result = next(m for m in view.meals if m.id == meal.id)
            uow.commit()
            return result


class DeleteMeal(UseCase):
    """Remove an empty meal. A meal with line items is never deleted implicitly."""

    def execute(self, meal_id: int) -> None:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            meal = uow.day_logs.get_meal(meal_id)
            if meal is None:
                raise NotFound(f"meal {meal_id} not found")
            if meal.line_items:
                raise Conflict(
                    f"meal {meal_id} still has {len(meal.line_items)} line item(s); "
                    "delete or move them first"
                )
            uow.audit.record(
                "meal.delete",
                "meal",
                str(meal.id),
                {"name": meal.name, "date": meal.day_log.date.isoformat()},
            )
            uow.day_logs.delete_meal(meal)
            uow.commit()


def _item_view(uow: UnitOfWork, li: orm.LineItem, day: date) -> dto.LineItemView:
    macros = uow.day_logs.line_item_macros(day).get(li.id)
    return line_item_view(li, macros, li.consumable)


class AddLineItem(UseCase):
    def execute(
        self, meal_id: int, item: LineItemInput, *, origin: str = "manual", is_draft: bool = False
    ) -> dto.LineItemView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            meal = uow.day_logs.get_meal(meal_id)
            if meal is None:
                raise NotFound(f"meal {meal_id} not found")
            consumable = uow.products.get_consumable(item.consumable_id)
            if consumable is None:
                raise NotFound(f"consumable {item.consumable_id} not found")
            base, base_unit, portion_id = resolve_base(uow, consumable, item)
            position = (max((li.position for li in meal.line_items), default=0)) + 1
            li = uow.day_logs.add_line_item(
                orm.LineItem(
                    meal_id=meal.id,
                    position=position,
                    consumable_id=consumable.id,
                    portion_id=portion_id,
                    unit_code=item.unit_code,
                    amount=item.amount,
                    base_amount=base,
                    base_unit=base_unit,
                    amount_estimated=item.amount_estimated,
                    estimated=item.estimated,
                    raw_text=item.raw_text,
                    origin=origin,
                    is_draft=is_draft,
                )
            )
            uow.flush()
            view = _item_view(uow, li, meal.day_log.date)
            uow.commit()
            return view


class UpdateLineItem(UseCase):
    """Change amount/unit/portion or re-assign the consumable (review list).

    Re-assigning keeps the frozen base amount unless a new amount is given — the
    quantity eaten is historical fact, the product is the correction.
    """

    def execute(self, item_id: int, changes: dict[str, Any]) -> dto.LineItemView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            li = uow.day_logs.get_line_item(item_id)
            if li is None:
                raise NotFound(f"line item {item_id} not found")
            diff: dict[str, Any] = {}
            consumable = li.consumable
            if (
                changes.get("consumable_id") is not None
                and changes["consumable_id"] != li.consumable_id
            ):
                new_c = uow.products.get_consumable(int(changes["consumable_id"]))
                if new_c is None:
                    raise NotFound("consumable not found")
                diff["consumable_id"] = [li.consumable_id, new_c.id]
                li.consumable_id = new_c.id
                li.consumable = new_c
                consumable = new_c
            if changes.get("amount") is not None or changes.get("unit_code") is not None:
                inp = LineItemInput(
                    consumable_id=consumable.id,
                    amount=float(
                        changes.get("amount", li.amount if li.amount is not None else 0.0)
                    ),
                    unit_code=str(changes.get("unit_code") or li.unit_code or "g"),
                    portion_id=changes.get("portion_id", li.portion_id),
                )
                base, base_unit, portion_id = resolve_base(uow, consumable, inp)
                diff["amount"] = [li.amount, inp.amount]
                li.amount, li.unit_code, li.portion_id = inp.amount, inp.unit_code, portion_id
                li.base_amount, li.base_unit = base, base_unit
            for key in ("estimated", "amount_estimated"):
                if key in changes and changes[key] is not None:
                    setattr(li, key, bool(changes[key]))
                    diff[key] = changes[key]
            uow.audit.record("line_item.update", "line_item", str(li.id), diff)
            uow.flush()
            view = _item_view(uow, li, li.meal.day_log.date)
            uow.commit()
            return view


class DeleteLineItem(UseCase):
    def execute(self, item_id: int) -> None:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            li = uow.day_logs.get_line_item(item_id)
            if li is None:
                raise NotFound(f"line item {item_id} not found")
            uow.audit.record(
                "line_item.delete", "line_item", str(li.id), {"consumable_id": li.consumable_id}
            )
            uow.day_logs.delete_line_item(li)
            uow.commit()


def freeze_band(uow: UnitOfWork, d: orm.DayLog) -> None:
    if d.target_band_id is None:
        band = uow.target_bands.for_date(
            d.date, TrainingType(d.training_type) if d.training_type else None
        )
        if band is not None:
            d.target_band_id = band.id


class CloseDay(UseCase):
    def execute(self, day: date) -> dto.DayView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            d = _day_or_404(uow, day)
            if d.reliable is None:
                raise ValidationFailed("set 'reliable' before closing the day")
            if (
                any(li.is_draft for m in d.meals for li in m.line_items)
                or d.status == DayStatus.DRAFT.value
            ):
                raise Conflict("day has draft items; approve or discard them first")
            d.status = DayStatus.CLOSED.value
            freeze_band(uow, d)
            uow.audit.record("day.close", "day_log", str(d.id), {"date": day.isoformat()})
            uow.flush()
            view = build_day_view(uow, d)
            uow.commit()
            return view


class ReopenDay(UseCase):
    def execute(self, day: date) -> dto.DayView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            d = _day_or_404(uow, day)
            d.status = DayStatus.OPEN.value
            uow.audit.record("day.reopen", "day_log", str(d.id), {"date": day.isoformat()})
            uow.flush()
            view = build_day_view(uow, d)
            uow.commit()
            return view


# ── day thread (ADR 0010) ───────────────────────────────────────────────────


def _message_view(
    m: orm.DayMessage, capture: orm.Capture | None, transcript: str | None = None
) -> dto.DayMessageView:
    return dto.DayMessageView(
        id=str(m.id),
        role=m.role,
        kind=m.kind,
        content=m.content,
        created_at=m.created_at,
        processing_state=capture.status if capture is not None else None,
        capture_id=capture.id if capture is not None else None,
        capture_kind=capture.kind if capture is not None else None,
        attachment_id=capture.attachment_id if capture is not None else None,
        attachment_mime=(
            capture.attachment.mime
            if capture is not None and capture.attachment is not None
            else None
        ),
        transcript=transcript,
    )


class GetDayThread(UseCase):
    def execute(self, day: date) -> list[dto.DayMessageView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            messages = list(uow.day_messages.thread(day))
            linked = {m.capture_id for m in messages if m.capture_id}
            out: list[dto.DayMessageView] = []
            for m in messages:
                cap = uow.captures.get(m.capture_id) if m.capture_id else None
                tr = uow.captures.transcript_for(cap.id) if cap is not None else None
                out.append(_message_view(m, cap, tr.text if tr else None))
            # captures that arrived without a thread message (uploads, voice notes)
            for cap in uow.captures.list(target_date=day):
                if cap.id in linked or cap.product_id is not None:
                    continue
                tr = uow.captures.transcript_for(cap.id)
                text = cap.text or (tr.text if tr and tr.text else "") or f"[{cap.kind}]"
                out.append(
                    dto.DayMessageView(
                        id=f"capture:{cap.id}",
                        role=MessageRole.USER.value,
                        kind=MessageKind.TEXT.value,
                        content=text,
                        created_at=cap.captured_at,
                        processing_state=cap.status,
                        capture_id=cap.id,
                        capture_kind=cap.kind,
                        attachment_id=cap.attachment_id,
                        attachment_mime=cap.attachment.mime if cap.attachment else None,
                        transcript=tr.text if tr else None,
                    )
                )
            out.sort(key=lambda m: m.created_at)
            return out


class AddDayMessage(UseCase):
    """A text message on a day = a capture with a target date + its thread row.

    If the day already has draft items or is locked by a running agent, a
    ``follow_up`` run is queued so the new information is processed incrementally.
    """

    def execute(self, day: date, text: str) -> dto.DayMessageView:
        self.ctx.require(SCOPE_WRITE)
        if not text.strip():
            raise ValidationFailed("message text is required")
        with self._uow() as uow:
            ts = now()
            digest = hashlib.sha256(
                f"{day.isoformat()}|{text.strip()}|{ts.isoformat()}".encode()
            ).hexdigest()
            capture = uow.captures.add(
                orm.Capture(
                    tenant_id=self.ctx.tenant_id,
                    user_id=self.ctx.user_id,
                    kind=CaptureKind.TEXT.value,
                    captured_at=ts,
                    target_date=day,
                    text=text.strip(),
                    status=CaptureStatus.NEW.value,
                    content_hash=digest,
                )
            )
            message = uow.day_messages.add(
                orm.DayMessage(
                    tenant_id=self.ctx.tenant_id,
                    date=day,
                    role=MessageRole.USER.value,
                    kind=MessageKind.TEXT.value,
                    content=text.strip(),
                    capture_id=capture.id,
                    created_at=ts,
                )
            )
            queue_follow_up_if_needed(uow, self.ctx, day, [capture.id], ts)
            view = _message_view(message, capture)
            uow.commit()
            return view
