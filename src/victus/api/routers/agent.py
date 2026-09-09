"""Agent runs (on-demand processing, SPEC R50) and per-day locks (R39)."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from victus.api.deps import Ctx, Uow, get_config
from victus.api.schemas.inbox import (
    AgentLockOut,
    AgentRunIn,
    AgentRunOut,
    AgentStatusOut,
    UnlockOut,
)
from victus.application.tenant_context import SCOPE_ADMIN, SCOPE_AGENT_WRITE, SCOPE_READ
from victus.application.use_cases import agent as uc
from victus.config.server import ServerConfig

router = APIRouter(tags=["agent"])


@router.get("/agent/status", response_model=AgentStatusOut, summary="Is a runner available?")
def agent_status(ctx: Ctx, cfg: Annotated[ServerConfig, Depends(get_config)]) -> AgentStatusOut:
    """Whether queueing a run would reach anyone (R67).

    Queued runs are picked up by the worker, which needs a model key. Without one the
    web app hands the job to the user's own Claude over MCP instead of queueing a run
    nobody would collect. No key material is exposed, only the state.
    """
    ctx.require(SCOPE_READ)
    if not cfg.agent.enabled:
        runner = "disabled"
    elif cfg.providers.anthropic_api_key is None:
        runner = "no_key"
    else:
        runner = "ready"
    return AgentStatusOut(runner=runner, model=cfg.agent.model if runner == "ready" else None)


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
