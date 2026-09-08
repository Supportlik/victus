"""Agent runs (on-demand processing, SPEC R50) and per-day locks (R39)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from victus.api.deps import Ctx, Uow
from victus.api.schemas.inbox import AgentLockOut, AgentRunIn, AgentRunOut, UnlockOut
from victus.application.tenant_context import SCOPE_ADMIN, SCOPE_AGENT_WRITE
from victus.application.use_cases import agent as uc

router = APIRouter(tags=["agent"])


@router.post("/agent/runs", response_model=AgentRunOut, status_code=status.HTTP_202_ACCEPTED)
def queue_run(body: AgentRunIn, ctx: Ctx, uow: Uow) -> AgentRunOut:
    run = uc.QueueAgentRun(uow, ctx).execute(
        body.mode, captures=body.captures, start=body.from_, end=body.to
    )
    return AgentRunOut.model_validate(run)


@router.get("/agent/runs", response_model=list[AgentRunOut])
def list_runs(
    ctx: Ctx,
    uow: Uow,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[AgentRunOut]:
    rows = uc.ListAgentRuns(uow, ctx).execute(limit=limit, status=status_)
    return [AgentRunOut.model_validate(r) for r in rows]


@router.get("/agent/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: str, ctx: Ctx, uow: Uow) -> AgentRunOut:
    return AgentRunOut.model_validate(uc.GetAgentRun(uow, ctx).execute(run_id))


@router.post("/agent/runs/{run_id}/cancel", response_model=AgentRunOut)
def cancel_run(run_id: str, ctx: Ctx, uow: Uow) -> AgentRunOut:
    return AgentRunOut.model_validate(uc.CancelAgentRun(uow, ctx).execute(run_id))


@router.get("/agent/locks", response_model=list[AgentLockOut])
def list_locks(ctx: Ctx, uow: Uow) -> list[AgentLockOut]:
    return [AgentLockOut.model_validate(lk) for lk in uc.ListAgentLocks(uow, ctx).execute()]


@router.delete("/agent/locks/{day}", response_model=UnlockOut)
def force_unlock(day: date, ctx: Ctx, uow: Uow) -> UnlockOut:
    if not (ctx.has_scope(SCOPE_ADMIN) or ctx.has_scope(SCOPE_AGENT_WRITE)):
        ctx.require(SCOPE_AGENT_WRITE)
    released = uc.ForceUnlockDay(uow, ctx).execute(day)
    return UnlockOut(date=day, released=released)
