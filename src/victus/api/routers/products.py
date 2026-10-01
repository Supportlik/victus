"""Products, portions and text matching.

Catalogue writes go through the doors of :mod:`victus.application.use_cases.proposals`
(ADR 0013): with ``write`` and ``approve`` the value is written (``201``/``200``/``204``),
without ``approve`` the same request is filed as a proposal a person decides and the
answer is ``202 Accepted`` with the proposal, the way the MCP tools behave.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import (
    MatchCandidateOut,
    PortionOut,
    ProductOut,
    ProductUsageOut,
)
from victus.api.schemas.inbox import ProposalOut
from victus.api.schemas.requests import (
    MatchIn,
    PortionIn,
    PortionPatch,
    ProductIn,
    ProductPatch,
    ProductVersionIn,
)
from victus.application import dto
from victus.application.use_cases import products as uc
from victus.application.use_cases import proposals as doors
from victus.application.use_cases._base import can_decide

router = APIRouter(tags=["products"])


def _out(p: object) -> ProductOut:
    return ProductOut.model_validate(asdict(p))  # type: ignore[call-overload]


#: How a catalogue write answers when it was filed as a proposal instead of applied.
_PROPOSED: dict[int | str, dict[str, object]] = {
    status.HTTP_202_ACCEPTED: {
        "model": ProposalOut,
        "description": "Filed as a proposal: the caller holds no `approve` (ADR 0013).",
    }
}


def _proposed(view: dto.ProductProposalView) -> JSONResponse:
    return JSONResponse(
        ProposalOut.model_validate(view).model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/products", response_model=list[ProductOut])
def search_products(
    ctx: Ctx,
    uow: Uow,
    q: Annotated[
        str,
        Query(
            description="Search over name and brand, ranked by the name: exact, prefix, "
            "word prefix, then substring; the fuzzy matcher adds candidates."
        ),
    ] = "",
    category: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[
        int,
        Query(ge=0, description="Skip this many rows, so a catalogue above the cap can be paged."),
    ] = 0,
    on: Annotated[
        date | None,
        Query(description="Return the version of each product that applied on this day (R70)."),
    ] = None,
) -> list[ProductOut]:
    rows = uc.SearchProducts(uow, ctx).execute(
        q, category_id=category, limit=limit, offset=offset, on=on
    )
    return [_out(p) for p in rows]


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    responses=_PROPOSED,
)
def create_product(body: ProductIn, ctx: Ctx, uow: Uow) -> ProductOut | JSONResponse:
    """Create a product; without `approve` a `new` proposal is filed instead (`202`)."""
    view = doors.create_or_propose_product(uow, ctx, uc.ProductInput(**body.model_dump()))
    if isinstance(view, dto.ProductProposalView):
        return _proposed(view)
    return _out(view)


@router.post("/products/match", response_model=list[MatchCandidateOut])
def match_products(body: MatchIn, ctx: Ctx, uow: Uow) -> list[MatchCandidateOut]:
    cands = uc.MatchText(uow, ctx).execute(body.text, limit=body.limit)
    return [
        MatchCandidateOut(
            consumable_id=c.consumable_id,
            name=c.name,
            kind=c.kind.value,
            tier=c.tier,
            score=c.score,
        )
        for c in cands
    ]


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, ctx: Ctx, uow: Uow) -> ProductOut:
    return _out(uc.GetProduct(uow, ctx).execute(product_id))


@router.get("/products/{product_id}/versions", response_model=list[ProductOut])
def product_versions(product_id: int, ctx: Ctx, uow: Uow) -> list[ProductOut]:
    """Every version of this product, oldest first."""
    return [_out(p) for p in uc.ProductVersions(uow, ctx).execute(product_id)]


@router.post(
    "/products/{product_id}/versions",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    responses=_PROPOSED,
)
def new_product_version(
    product_id: int, body: ProductVersionIn, ctx: Ctx, uow: Uow
) -> ProductOut | JSONResponse:
    """Record changed values from a day on; the old version keeps the days before it.

    Without `approve` the new version is filed as a proposal (`202`).
    """
    view = doors.version_or_propose_product_version(
        uow, ctx, product_id, body.valid_from, dict(body.changes or {})
    )
    if isinstance(view, dto.ProductProposalView):
        return _proposed(view)
    return _out(view)


@router.get("/products/{product_id}/usage", response_model=ProductUsageOut)
def product_usage(
    product_id: int,
    ctx: Ctx,
    uow: Uow,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ProductUsageOut:
    """The days this product was logged on, newest first, plus `item_count` over all of them.

    The id may also be the one-off consumable a pending `new` proposal is logged against,
    which is how that proposal shows the day and the meal it was eaten in.
    """
    return ProductUsageOut.model_validate(
        uc.GetProductUsage(uow, ctx).execute(product_id, limit=limit)
    )


@router.patch("/products/{product_id}", response_model=ProductOut, responses=_PROPOSED)
def update_product(
    product_id: int, body: ProductPatch, ctx: Ctx, uow: Uow
) -> ProductOut | JSONResponse:
    """Correct a product; without `approve` the correction is filed as a proposal (`202`)."""
    view = doors.update_or_propose_product(
        uow, ctx, product_id, body.model_dump(exclude_unset=True)
    )
    if isinstance(view, dto.ProductProposalView):
        return _proposed(view)
    return _out(view)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, ctx: Ctx, uow: Uow) -> Response:
    uc.DeleteProduct(uow, ctx).execute(product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products/{product_id}/portions", response_model=list[PortionOut])
def list_portions(product_id: int, ctx: Ctx, uow: Uow) -> list[PortionOut]:
    return [
        PortionOut.model_validate(p) for p in uc.GetProduct(uow, ctx).execute(product_id).portions
    ]


@router.post(
    "/products/{product_id}/portions",
    response_model=PortionOut,
    status_code=status.HTTP_201_CREATED,
    responses=_PROPOSED,
)
def add_portion(product_id: int, body: PortionIn, ctx: Ctx, uow: Uow) -> PortionOut | JSONResponse:
    """Add a portion; without `approve` the addition is filed as a proposal (`202`)."""
    view = doors.add_or_propose_portion(uow, ctx, product_id, body.model_dump())
    if isinstance(view, dto.ProductProposalView):
        return _proposed(view)
    return PortionOut.model_validate(view)


@router.patch("/portions/{portion_id}", response_model=PortionOut, responses=_PROPOSED)
def update_portion(
    portion_id: int, body: PortionPatch, ctx: Ctx, uow: Uow
) -> PortionOut | JSONResponse:
    """Correct a portion; without `approve` the correction is filed as a proposal (`202`)."""
    changes = body.model_dump(exclude_unset=True)
    if can_decide(ctx):
        # Applied directly so an explicit null (clearing a description) is kept.
        return PortionOut.model_validate(uc.UpdatePortion(uow, ctx).execute(portion_id, changes))
    view = doors.update_or_propose_portion(uow, ctx, portion_id, changes)
    if isinstance(view, dto.ProductProposalView):
        return _proposed(view)
    return PortionOut.model_validate(view)


@router.delete(
    "/portions/{portion_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_PROPOSED
)
def delete_portion(portion_id: int, ctx: Ctx, uow: Uow) -> Response:
    """Remove a portion; without `approve` the removal is filed as a proposal (`202`)."""
    view = doors.delete_or_propose_portion(uow, ctx, portion_id)
    if view is not None:
        return _proposed(view)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
