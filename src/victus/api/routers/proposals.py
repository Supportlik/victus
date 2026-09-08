"""Product change proposals: list, inspect, approve or reject."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from victus.api.deps import Ctx, Uow
from victus.api.schemas.inbox import ProposalDecisionIn, ProposalOut
from victus.application.use_cases import proposals as uc

router = APIRouter(tags=["proposals"])


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    ctx: Ctx,
    uow: Uow,
    status_: Annotated[str | None, Query(alias="status")] = "pending",
    product_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ProposalOut]:
    rows = uc.ListProposals(uow, ctx).execute(
        status=status_ or None, product_id=product_id, limit=limit
    )
    return [ProposalOut.model_validate(p) for p in rows]


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
def get_proposal(proposal_id: str, ctx: Ctx, uow: Uow) -> ProposalOut:
    return ProposalOut.model_validate(uc.GetProposal(uow, ctx).execute(proposal_id))


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
def approve_proposal(
    proposal_id: str, ctx: Ctx, uow: Uow, body: ProposalDecisionIn | None = None
) -> ProposalOut:
    view = uc.DecideProposal(uow, ctx).execute(
        proposal_id,
        approve=True,
        changes=body.changes if body else None,
        fields=body.fields if body else None,
    )
    return ProposalOut.model_validate(view)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(proposal_id: str, ctx: Ctx, uow: Uow) -> ProposalOut:
    return ProposalOut.model_validate(
        uc.DecideProposal(uow, ctx).execute(proposal_id, approve=False)
    )
