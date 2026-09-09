"""Weight entries and body measurements (manual only; the scale sync owns the weight series)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import BodyMeasurementOut, WeightEntryOut
from victus.api.schemas.requests import BodyMeasurementIn, WeightIn
from victus.application.use_cases import body as body_uc
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


@router.get("/body-measurements", response_model=list[BodyMeasurementOut])
def list_body(
    ctx: Ctx,
    uow: Uow,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
) -> list[BodyMeasurementOut]:
    """Tape-measure sessions, oldest first (R76)."""
    rows = body_uc.ListBodyMeasurements(uow, ctx).execute(from_, to, limit)
    return [BodyMeasurementOut.model_validate(r) for r in rows]


@router.post(
    "/body-measurements", response_model=BodyMeasurementOut, status_code=status.HTTP_201_CREATED
)
def add_body(body: BodyMeasurementIn, ctx: Ctx, uow: Uow) -> BodyMeasurementOut:
    """Record one session. Every circumference is optional; at least one is required."""
    return BodyMeasurementOut.model_validate(
        body_uc.AddBodyMeasurement(uow, ctx).execute(body_uc.BodyInput(**body.model_dump()))
    )


@router.delete("/body-measurements/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_body(row_id: int, ctx: Ctx, uow: Uow) -> Response:
    body_uc.DeleteBodyMeasurement(uow, ctx).execute(row_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
