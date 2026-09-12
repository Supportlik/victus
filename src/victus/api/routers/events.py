"""Server-sent events: an open page is told that its tenant's data changed (R83).

The stream is a thin shell around :mod:`victus.application.use_cases.events`. It
polls the tenant's audit cursor server-side — one ``MAX(id)`` per connected client
per ``events.poll_seconds`` — and pushes when it moves, so no client has to poll.

Each message carries ``id:`` = the cursor it reflects. A browser sends the last one
back as ``Last-Event-ID`` when it reconnects (``?cursor=`` does the same for a client
that is not an ``EventSource``), so a reconnect resumes instead of replaying.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from victus.api.deps import Config, Ctx, Uow
from victus.application import dto
from victus.application.errors import FeatureDisabled
from victus.application.tenant_context import SCOPE_CAPTURE_READ, SCOPE_READ, TenantContext
from victus.application.use_cases import events as uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import EventsConfig

router = APIRouter(tags=["events"])

#: Named so a reader of a network log can tell them apart at a glance.
HELLO = "hello"
CHANGE = "change"
HEARTBEAT = "heartbeat"


def _message(event: str, cursor: int, data: dict[str, object]) -> str:
    """One SSE frame. ``id`` is the cursor, which is what makes a resume possible."""
    body = json.dumps(data, separators=(",", ":"), default=str)
    return f"id: {cursor}\nevent: {event}\ndata: {body}\n\n"


def _change(view: dto.ChangeView) -> dict[str, object]:
    """What moved. ``targets`` names action, target type and target id — never the
    audit ``diff``, so an open page learns that the day changed, not what was eaten."""
    return {
        "cursor": view.cursor,
        "counts": asdict(view.counts),
        "targets": [asdict(t) for t in view.targets],
        "truncated": view.truncated,
    }


def _resume_from(request: Request, cursor: int | None) -> int | None:
    """Where the client left off: the SSE reconnect header first, then ``?cursor=``.

    An unreadable header is ignored rather than refused — a reconnect must not fail
    because a proxy mangled it; the client simply starts from now.
    """
    header = request.headers.get("last-event-id")
    if header is not None:
        try:
            return max(0, int(header.strip()))
        except ValueError:
            return cursor
    return cursor


async def _stream(
    request: Request,
    uow_factory: UowFactory,
    ctx: TenantContext,
    cfg: EventsConfig,
    resume_from: int | None,
) -> AsyncIterator[str]:
    """Poll the cursor until the client goes away.

    Every database call runs in a worker thread and opens its own unit of work, so
    nothing holds a session between two polls, and the loop always waits — it can
    never turn into a spin.
    """
    start = await run_in_threadpool(uc.InboxState(uow_factory, ctx).execute)
    # A resuming client is greeted at *its* cursor, never at the current one: the
    # greeting is where the stream starts, so anything in between is still to come.
    cursor = start.cursor if resume_from is None else min(resume_from, start.cursor)
    yield _message(HELLO, cursor, {"cursor": cursor, "counts": asdict(start.counts)})
    silence = 0.0
    while True:
        if await request.is_disconnected():
            return
        latest = await run_in_threadpool(uc.ChangeCursor(uow_factory, ctx).execute)
        if latest > cursor:
            view = await run_in_threadpool(uc.ChangesSince(uow_factory, ctx).execute, cursor)
            cursor = view.cursor
            silence = 0.0
            yield _message(CHANGE, cursor, _change(view))
        elif silence >= cfg.heartbeat_seconds:
            silence = 0.0
            yield _message(HEARTBEAT, cursor, {"cursor": cursor})
        await anyio.sleep(cfg.poll_seconds)
        silence += cfg.poll_seconds


@router.get(
    "/events",
    summary="Changes to this tenant, pushed",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "The event stream"},
        503: {"description": "Server-sent events are disabled (`events.enabled`)"},
    },
)
async def events(
    request: Request,
    ctx: Ctx,
    uow: Uow,
    config: Config,
    cursor: Annotated[int | None, Query(ge=0)] = None,
) -> StreamingResponse:
    """Open a stream of `hello`, `change` and `heartbeat` events for the tenant.

    Reading the four badge counts needs `capture:read` beside `read`, because one of
    them counts captures; a token without it falls back to the list endpoints it may
    read. The payload never carries an audit `diff` — action, target type and target
    id only.
    """
    if not config.events.enabled:
        raise FeatureDisabled("server-sent events are disabled on this server")
    # Refuse here, where a refusal can still be a status code: once the stream has
    # started the response is on its way and nothing can be taken back.
    ctx.require(SCOPE_READ)
    ctx.require(SCOPE_CAPTURE_READ)
    return StreamingResponse(
        _stream(request, uow, ctx, config.events, _resume_from(request, cursor)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers proxied responses by default, which holds every event
            # back until the buffer fills — for a push channel that is a failure.
            "X-Accel-Buffering": "no",
        },
    )
