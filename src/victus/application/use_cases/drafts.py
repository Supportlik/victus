"""Drafts: list, summary, approval and discard (ADR 0003)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from victus.application import dto
from victus.application.errors import NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_APPROVE, SCOPE_READ
from victus.application.use_cases._base import UseCase, now
from victus.application.use_cases.day_logs import (
    LineItemInput,
    build_day_view,
    freeze_band,
    resolve_base,
)
from victus.domain.values import CaptureStatus, DayStatus
from victus.infrastructure.db import orm


@dataclass(frozen=True, slots=True)
class DraftCorrection:
    line_item_id: int
    amount: float | None = None
    unit_code: str | None = None
    consumable_id: int | None = None
    delete: bool = False


def _fmt(v: float | None, digits: int = 0) -> str:
    if v is None:
        return "–"
    return f"{v:,.{digits}f}"


def draft_markdown(view: dto.DayView) -> str:
    """The chat summary of one drafted day (see docs/AGENT.md, *Summary format*)."""
    est = sum(1 for m in view.meals for li in m.line_items if li.estimated or li.amount_estimated)
    head = (
        f"### {view.date.isoformat()} · {view.status} · {_fmt(view.macros.kcal)} kcal · "
        f"protein {_fmt(view.macros.protein, 1)} g"
    )
    if est:
        head += f" · ⚠️ {est} estimate{'s' if est != 1 else ''}"
    lines = [
        head,
        "",
        "| Meal | Item | Quantity | kcal | Confidence | Draft |",
        "|---|---|---|---|---|---|",
    ]
    for meal in view.meals:
        for li in meal.line_items:
            amount = _fmt(li.amount, 1) if li.amount is not None else _fmt(li.base_amount)
            qty = f"{amount} {li.unit_code or li.base_unit}"
            if li.estimated or li.amount_estimated:
                qty += " ⚠️"
            conf = f"{li.confidence:.2f}" if li.confidence is not None else "–"
            draft = "yes" if li.is_draft else ""
            cells = (meal.name, li.consumable_name, qty, _fmt(li.kcal), conf, draft)
            lines.append("| " + " | ".join(cells) + " |")
    if view.findings:
        lines.append("")
        for f in view.findings:
            lines.append(f"- {f.code}: {f.message}")
    lines.append("")
    lines.append(f'Approve? Reply "approve {view.date.isoformat()}" or give corrections.')
    return "\n".join(lines)


class ListDrafts(UseCase):
    def execute(self) -> list[dto.DraftListEntryView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            out = []
            for d in uow.day_logs.draft_days():
                items = [li for m in d.meals for li in m.line_items]
                drafts = [li for li in items if li.is_draft]
                macros = uow.day_logs.macros_for(d.date)
                out.append(
                    dto.DraftListEntryView(
                        date=d.date,
                        status=d.status,
                        draft_items=len(drafts),
                        kcal=macros.kcal if macros else None,
                        estimated_items=sum(
                            1 for li in items if li.estimated or li.amount_estimated
                        ),
                        created_by=d.created_by_kind,
                    )
                )
            return out


class DraftSummary(UseCase):
    def execute(self, day: date) -> dto.DraftSummaryView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            d = uow.day_logs.get_by_date(day)
            if d is None:
                raise NotFound(f"no day log for {day.isoformat()}")
            view = build_day_view(uow, d)
            return dto.DraftSummaryView(date=day, markdown=draft_markdown(view), day=view)


def _apply_corrections(
    uow: UnitOfWork, d: orm.DayLog, corrections: list[DraftCorrection]
) -> list[dict[str, object]]:
    by_id = {li.id: li for m in d.meals for li in m.line_items}
    applied: list[dict[str, object]] = []
    for c in corrections:
        li = by_id.get(c.line_item_id)
        if li is None:
            raise NotFound(f"line item {c.line_item_id} is not part of {d.date.isoformat()}")
        if c.delete:
            li.meal.line_items.remove(li)  # delete-orphan cascade removes the row
            applied.append({"line_item_id": c.line_item_id, "delete": True})
            continue
        consumable = li.consumable
        if c.consumable_id is not None and c.consumable_id != li.consumable_id:
            new_c = uow.products.get_consumable(c.consumable_id)
            if new_c is None:
                raise NotFound(f"consumable {c.consumable_id} not found")
            li.consumable_id = new_c.id
            li.consumable = new_c
            consumable = new_c
        if c.amount is not None or c.unit_code is not None:
            inp = LineItemInput(
                consumable_id=consumable.id,
                amount=c.amount if c.amount is not None else float(li.amount or 0.0),
                unit_code=c.unit_code or li.unit_code or "g",
                portion_id=li.portion_id if c.unit_code in (None, li.unit_code) else None,
            )
            base, base_unit, portion_id = resolve_base(uow, consumable, inp)
            li.amount, li.unit_code, li.portion_id = inp.amount, inp.unit_code, portion_id
            li.base_amount, li.base_unit = base, base_unit
            # A person corrected the quantity: it is no longer an estimate.
            li.amount_estimated = False
        applied.append(
            {"line_item_id": c.line_item_id, "amount": c.amount, "consumable_id": c.consumable_id}
        )
    return applied


class ApproveDay(UseCase):
    """Apply corrections, clear draft flags, freeze the band, mark captures processed."""

    def execute(self, day: date, corrections: list[DraftCorrection], *, close: bool) -> dto.DayView:
        self.ctx.require(SCOPE_APPROVE)
        with self._uow() as uow:
            d = uow.day_logs.get_by_date(day)
            if d is None:
                raise NotFound(f"no day log for {day.isoformat()}")
            applied = _apply_corrections(uow, d, corrections)
            uow.flush()
            capture_ids: set[str] = set()
            for m in d.meals:
                for li in m.line_items:
                    li.is_draft = False  # `estimated` stays: the estimate was checked, not removed
                    if li.source_capture_id:
                        capture_ids.add(li.source_capture_id)
            if d.reliable is None:
                d.reliable = True
            d.status = DayStatus.CLOSED.value if close else DayStatus.OPEN.value
            if close:
                freeze_band(uow, d)
            d.approved_at = now()
            d.approved_by = self.ctx.actor_id
            for cid in capture_ids:
                cap = uow.captures.get(cid)
                if cap is not None:
                    cap.status = CaptureStatus.PROCESSED.value
                    cap.processed_at = d.approved_at
            for cap in uow.captures.list(target_date=day):
                if cap.status in (CaptureStatus.ASSIGNED.value, CaptureStatus.IN_PROGRESS.value):
                    cap.status = CaptureStatus.PROCESSED.value
                    cap.processed_at = d.approved_at
            uow.audit.record(
                "day.approve", "day_log", str(d.id), {"corrections": applied, "close": close}
            )
            uow.flush()
            view = build_day_view(uow, d)
            uow.commit()
            return view


class DiscardDraft(UseCase):
    def execute(self, day: date) -> int:
        self.ctx.require(SCOPE_APPROVE)
        with self._uow() as uow:
            d = uow.day_logs.get_by_date(day)
            if d is None:
                raise NotFound(f"no day log for {day.isoformat()}")
            removed = 0
            for m in list(d.meals):
                for li in list(m.line_items):
                    if li.is_draft:
                        m.line_items.remove(li)  # delete-orphan cascade
                        removed += 1
            uow.flush()
            if d.status == DayStatus.DRAFT.value:
                remaining = sum(len(m.line_items) for m in d.meals)
                if remaining == 0:
                    uow.day_logs.delete_day(d)
                else:
                    d.status = DayStatus.OPEN.value
            elif removed == 0:
                raise ValidationFailed("nothing to discard")
            uow.audit.record("day.discard_draft", "day_log", day.isoformat(), {"removed": removed})
            uow.commit()
            return removed
