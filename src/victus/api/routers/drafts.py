"""Drafts: list, summary, approve, discard."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from victus.api.deps import Ctx, Uow
from victus.api.routers._convert import day_out, line_item_out
from victus.api.schemas.common import DayOut, LineItemOut, Out
from victus.api.schemas.requests import ApproveIn, ApproveItemIn
from victus.application.use_cases import drafts as uc

router = APIRouter(tags=["drafts"])


class DraftListEntryOut(Out):
    date: date
    status: str
    draft_items: int
    kcal: float | None
    estimated_items: int
    created_by: str


class DraftSummaryOut(Out):
    date: date
    markdown: str
    day: DayOut


class DiscardOut(Out):
    removed: int


@router.get("/drafts", response_model=list[DraftListEntryOut])
def list_drafts(ctx: Ctx, uow: Uow) -> list[DraftListEntryOut]:
    return [DraftListEntryOut.model_validate(d) for d in uc.ListDrafts(uow, ctx).execute()]


@router.get("/drafts/{day}/summary", response_model=DraftSummaryOut)
def draft_summary(day: date, ctx: Ctx, uow: Uow) -> DraftSummaryOut:
    s = uc.DraftSummary(uow, ctx).execute(day)
    return DraftSummaryOut(date=s.date, markdown=s.markdown, day=day_out(s.day))


@router.post("/drafts/{day}/approve", response_model=DayOut)
def approve(day: date, body: ApproveIn, ctx: Ctx, uow: Uow) -> DayOut:
    corrections = [uc.DraftCorrection(**c.model_dump()) for c in body.corrections]
    return day_out(uc.ApproveDay(uow, ctx).execute(day, corrections, close=body.close))


@router.post("/line-items/{item_id}/approve", response_model=LineItemOut)
def approve_line_item(
    item_id: int, ctx: Ctx, uow: Uow, body: ApproveItemIn | None = None
) -> LineItemOut:
    fields = body.model_dump(exclude_none=True) if body is not None else {}
    meal_id = fields.pop("meal_id", None)
    meal_name = fields.pop("meal_name", None)
    correction = uc.DraftCorrection(line_item_id=item_id, **fields) if fields else None
    return line_item_out(
        uc.ApproveLineItem(uow, ctx).execute(
            item_id, correction, meal_id=meal_id, meal_name=meal_name
        )
    )


@router.post("/drafts/{day}/discard", response_model=DiscardOut)
def discard(day: date, ctx: Ctx, uow: Uow) -> DiscardOut:
    return DiscardOut(removed=uc.DiscardDraft(uow, ctx).execute(day))
