"""Day logs, meals, line items and the day thread."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from victus.api.deps import Ctx, Uow
from victus.api.routers._convert import day_out, day_summary_out, line_item_out, meal_out
from victus.api.schemas.common import DayMessageOut, DayOut, DaySummaryOut, LineItemOut, MealOut
from victus.api.schemas.requests import (
    DayCreate,
    DayFlags,
    DayMessageIn,
    LineItemIn,
    LineItemPatch,
    MealIn,
)
from victus.application.use_cases import day_logs as uc

router = APIRouter(tags=["days"])


@router.get("/days", response_model=list[DaySummaryOut])
def list_days(
    ctx: Ctx,
    uow: Uow,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[DaySummaryOut]:
    return [day_summary_out(d) for d in uc.ListDays(uow, ctx).execute(from_, to, status_)]


@router.get("/days/{day}", response_model=DayOut)
def get_day(day: date, ctx: Ctx, uow: Uow) -> DayOut:
    return day_out(uc.GetDay(uow, ctx).execute(day))


@router.post("/days/{day}", response_model=DayOut, status_code=status.HTTP_201_CREATED)
def create_day(day: date, body: DayCreate, ctx: Ctx, uow: Uow) -> DayOut:
    return day_out(
        uc.CreateDay(uow, ctx).execute(
            day, reliable=body.reliable, training_type=body.training_type, notes=body.notes
        )
    )


@router.put("/days/{day}", response_model=DayOut)
def update_day(day: date, body: DayFlags, ctx: Ctx, uow: Uow) -> DayOut:
    return day_out(uc.UpdateDayFlags(uow, ctx).execute(day, body.model_dump(exclude_unset=True)))


@router.post("/days/{day}/meals", response_model=MealOut, status_code=status.HTTP_201_CREATED)
def add_meal(day: date, body: MealIn, ctx: Ctx, uow: Uow) -> MealOut:
    return meal_out(uc.AddMeal(uow, ctx).execute(day, body.name, body.time))


@router.post(
    "/meals/{meal_id}/line-items", response_model=LineItemOut, status_code=status.HTTP_201_CREATED
)
def add_line_item(meal_id: int, body: LineItemIn, ctx: Ctx, uow: Uow) -> LineItemOut:
    return line_item_out(
        uc.AddLineItem(uow, ctx).execute(meal_id, uc.LineItemInput(**body.model_dump()))
    )


@router.patch("/line-items/{item_id}", response_model=LineItemOut)
def update_line_item(item_id: int, body: LineItemPatch, ctx: Ctx, uow: Uow) -> LineItemOut:
    return line_item_out(
        uc.UpdateLineItem(uow, ctx).execute(item_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/line-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line_item(item_id: int, ctx: Ctx, uow: Uow) -> Response:
    uc.DeleteLineItem(uow, ctx).execute(item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/days/{day}/close", response_model=DayOut)
def close_day(day: date, ctx: Ctx, uow: Uow) -> DayOut:
    return day_out(uc.CloseDay(uow, ctx).execute(day))


@router.post("/days/{day}/reopen", response_model=DayOut)
def reopen_day(day: date, ctx: Ctx, uow: Uow) -> DayOut:
    return day_out(uc.ReopenDay(uow, ctx).execute(day))


@router.get("/days/{day}/messages", response_model=list[DayMessageOut])
def day_thread(day: date, ctx: Ctx, uow: Uow) -> list[DayMessageOut]:
    return [DayMessageOut.model_validate(m) for m in uc.GetDayThread(uow, ctx).execute(day)]


@router.post(
    "/days/{day}/messages", response_model=DayMessageOut, status_code=status.HTTP_201_CREATED
)
def add_day_message(day: date, body: DayMessageIn, ctx: Ctx, uow: Uow) -> DayMessageOut:
    return DayMessageOut.model_validate(uc.AddDayMessage(uow, ctx).execute(day, body.text))
