"""Weight entries (manual additions only; the scale sync owns the series)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import WeightEntryOut
from victus.api.schemas.requests import WeightIn
from victus.application.use_cases import weights as uc

router = APIRouter(tags=["weight"])


@router.get("/weight", response_model=list[WeightEntryOut])
def list_weight(
    ctx: Ctx,
    uow: Uow,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> list[WeightEntryOut]:
    return [WeightEntryOut.model_validate(e) for e in uc.ListWeights(uow, ctx).execute(from_, to)]


@router.post("/weight", response_model=WeightEntryOut, status_code=status.HTTP_201_CREATED)
def add_weight(body: WeightIn, ctx: Ctx, uow: Uow) -> WeightEntryOut:
    return WeightEntryOut.model_validate(
        uc.AddManualWeight(uow, ctx).execute(body.measured_at, body.kg)
    )


@router.delete("/weight/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_weight(entry_id: int, ctx: Ctx, uow: Uow) -> Response:
    uc.DeleteManualWeight(uow, ctx).execute(entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
