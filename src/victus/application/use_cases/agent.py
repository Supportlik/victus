"""Agent runs, per-day locks, day context and draft creation (SPEC R37–R40, R49–R51).

Both runners — the in-house worker and an external Claude over MCP — go through
these use cases, so the lock rules and the draft schema are enforced in one
place. The model itself is never called here (see ``victus.agent``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import jsonschema

from victus.application import dto
from victus.application.errors import (
    Conflict,
    LockHeldByOtherRun,
    NotFound,
    RunNotActive,
    ValidationFailed,
)
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.schemas_loader import load_schema
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_CAPTURE_READ,
    SCOPE_READ,
    TenantContext,
)
from victus.application.use_cases._base import UowFactory, UseCase, now
from victus.application.use_cases._mappers import weekday_name
from victus.application.use_cases.captures import capture_view
from victus.application.use_cases.day_logs import (
    GetDayThread,
    LineItemInput,
    build_day_view,
    resolve_base,
)
from victus.application.use_cases.drafts import draft_markdown
from victus.application.use_cases.products import in_reference_unit
from victus.application.use_cases.proposals import NEW, PENDING, author_of
from victus.domain.services.food_query import one_off_name
from victus.domain.values import (
    AgentMode,
    CaptureStatus,
    DayStatus,
    MessageKind,
    MessageRole,
    RunStatus,
    TrainingType,
)
from victus.infrastructure.db import orm

ACTIVE_STATUSES = frozenset({RunStatus.QUEUED.value, RunStatus.RUNNING.value})
FINAL_STATUSES = frozenset(
    {
        RunStatus.FINISHED.value,
        RunStatus.BUDGET_EXCEEDED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    }
)


# ── views ────────────────────────────────────────────────────────────────────


def _session_view(s: orm.AgentSession) -> dto.AgentSessionView:
    return dto.AgentSessionView(
        date=s.date,
        model=s.model,
        prompt_version=s.prompt_version,
        input_tokens=s.input_tokens,
        output_tokens=s.output_tokens,
        cost_usd=s.cost_usd,
        outcome=s.outcome,
        started_at=s.started_at,
        finished_at=s.finished_at,
    )


def run_view(run: orm.AgentRun, sessions: Iterable[orm.AgentSession] = ()) -> dto.AgentRunView:
    return dto.AgentRunView(
        id=run.id,
        runner=run.runner,
        mode=run.mode,
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        captures=list(run.captures or []),
        days=[date.fromisoformat(d) for d in (run.days or [])],
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=run.cost_usd,
        model=run.model,
        prompt_version=run.prompt_version,
        summary_md=run.summary_md,
        error=run.error,
        sessions=[_session_view(s) for s in sessions],
    )


def _lock_view(lock: orm.AgentLock) -> dto.AgentLockView:
    return dto.AgentLockView(
        date=lock.date, runner=lock.runner, run_id=lock.run_id, locked_until=lock.locked_until
    )


def _mode(value: str) -> str:
    try:
        return AgentMode(value).value
    except ValueError as exc:
        raise ValidationFailed(f"unknown agent mode '{value}'") from exc


def _run_or_404(uow: UnitOfWork, run_id: str) -> orm.AgentRun:
    run = uow.agent.get_run(run_id)
    if run is None:
        raise NotFound(f"agent run {run_id} not found")
    return run


def _running_run(uow: UnitOfWork, run_id: str) -> orm.AgentRun:
    run = _run_or_404(uow, run_id)
    if run.status != RunStatus.RUNNING.value:
        raise RunNotActive(f"agent run {run_id} is {run.status}")
    return run


# ── run lifecycle ────────────────────────────────────────────────────────────


class QueueAgentRun(UseCase):
    """``POST /agent/runs``: queue a worker run; the worker picks it up within seconds (R50)."""

    def execute(
        self,
        mode: str = AgentMode.HISTORICAL.value,
        *,
        captures: list[str] | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> dto.AgentRunView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        mode = _mode(mode)
        if start and end and end < start:
            raise ValidationFailed("'to' must not be before 'from'")
        with self._uow() as uow:
            days: list[str] | None = None
            if start or end:
                s = start or end
                e = end or start
                assert s is not None and e is not None
                if (e - s).days > 366:
                    raise ValidationFailed("date range too large (max 366 days)")
                days = [(s + dt.timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]
            if captures:
                for cid in captures:
                    if uow.captures.get(cid) is None:
                        raise NotFound(f"capture {cid} not found")
            run = uow.agent.add_run(
                orm.AgentRun(
                    tenant_id=self.ctx.tenant_id,
                    runner="worker",
                    mode=mode,
                    status=RunStatus.QUEUED.value,
                    captures=list(captures or []),
                    days=days,
                )
            )
            uow.audit.record("agent.run.queue", "agent_run", run.id, {"mode": mode})
            view = run_view(run)
            uow.commit()
            return view


def resolve_run_days(uow: UnitOfWork, run: orm.AgentRun) -> list[date]:
    """Which days a run is about, oldest first (R49: one session per day)."""
    days: set[date] = {date.fromisoformat(d) for d in (run.days or [])}
    for cid in run.captures or []:
        cap = uow.captures.get(cid)
        if cap is not None and cap.target_date is not None:
            days.add(cap.target_date)
    if not days and run.mode in (AgentMode.HISTORICAL.value, AgentMode.BATCH.value):
        for cap in uow.captures.list(status=CaptureStatus.NEW.value):
            if cap.target_date is not None:
                days.add(cap.target_date)
    if run.mode in (AgentMode.HISTORICAL.value, AgentMode.BATCH.value) and (run.days or []):
        # an explicit range only counts days that actually have open captures
        with_captures = {
            c.target_date
            for c in uow.captures.list(status=CaptureStatus.NEW.value)
            if c.target_date is not None
        }
        days &= with_captures
    return sorted(days)


class BeginAgentRun(UseCase):
    """Take a run to ``running`` and lock its days.

    ``run_id`` given: the worker claims a queued run. ``run_id`` omitted: an
    external runner (MCP ``agent_run_start``) creates and starts a run in one step.
    Days whose lock is held elsewhere are skipped, never waited for.
    """

    def execute(
        self,
        *,
        run_id: str | None = None,
        runner: str = "worker",
        mode: str = AgentMode.HISTORICAL.value,
        dates: list[date] | None = None,
        captures: list[str] | None = None,
        lock_ttl_minutes: int = 5,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> dto.RunStartView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        if runner not in ("worker", "external"):
            raise ValidationFailed("runner must be 'worker' or 'external'")
        ts = now()
        with self._uow() as uow:
            if run_id is not None:
                run = _run_or_404(uow, run_id)
                if run.status != RunStatus.QUEUED.value:
                    raise RunNotActive(f"agent run {run_id} is {run.status}, not queued")
            else:
                run = uow.agent.add_run(
                    orm.AgentRun(
                        tenant_id=self.ctx.tenant_id,
                        runner=runner,
                        mode=_mode(mode),
                        status=RunStatus.QUEUED.value,
                        captures=list(captures or []),
                        days=[d.isoformat() for d in (dates or [])] or None,
                    )
                )
            days = resolve_run_days(uow, run)
            locked: list[date] = []
            skipped: dict[date, str] = {}
            for day in days:
                if uow.agent.try_acquire_lock(day, run.runner, run.id, lock_ttl_minutes, ts):
                    locked.append(day)
                else:
                    holder = uow.agent.lock_holder(day, ts)
                    skipped[day] = (
                        f"locked by {holder.runner} run {holder.run_id}" if holder else "locked"
                    )
            # duplicate queued follow-ups for the same days merge into this run
            if run.mode == AgentMode.FOLLOW_UP.value:
                for other in uow.agent.queued_runs():
                    if (
                        other.id != run.id
                        and other.mode == run.mode
                        and set(other.days or []) <= {d.isoformat() for d in locked}
                    ):
                        other.status = RunStatus.CANCELLED.value
                        other.error = f"merged into run {run.id}"
                        other.finished_at = ts
                        run.captures = sorted(set(run.captures or []) | set(other.captures or []))
            run.status = RunStatus.RUNNING.value
            run.started_at = ts
            run.days = [d.isoformat() for d in locked]
            run.model = model or run.model
            run.prompt_version = prompt_version or run.prompt_version
            uow.audit.record(
                "agent.run.begin",
                "agent_run",
                run.id,
                {"locked": [d.isoformat() for d in locked], "skipped": len(skipped)},
            )
            uow.flush()
            view = dto.RunStartView(run=run_view(run), locked_days=locked, skipped_days=skipped)
            uow.commit()
            return view


class AcquireDayLock(UseCase):
    """Add one more day to a running run (e.g. a capture re-targeted mid-run)."""

    def execute(self, run_id: str, day: date, *, lock_ttl_minutes: int = 5) -> bool:
        self.ctx.require(SCOPE_AGENT_WRITE)
        ts = now()
        with self._uow() as uow:
            run = _running_run(uow, run_id)
            ok = uow.agent.try_acquire_lock(day, run.runner, run.id, lock_ttl_minutes, ts)
            if ok and day.isoformat() not in (run.days or []):
                run.days = sorted([*(run.days or []), day.isoformat()])
            uow.commit()
            return ok


class ExtendDayLock(UseCase):
    def execute(self, run_id: str, day: date, *, lock_ttl_minutes: int = 5) -> bool:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            _running_run(uow, run_id)
            ok = uow.agent.extend_lock(day, run_id, lock_ttl_minutes, now())
            uow.commit()
            return ok


class ReleaseDayLock(UseCase):
    """Release a single day early (the run keeps going with its other days)."""

    def execute(self, run_id: str, day: date) -> bool:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            holder = uow.agent.lock_holder(day, now())
            if holder is not None and holder.run_id != run_id:
                raise LockHeldByOtherRun(f"{day.isoformat()} is locked by run {holder.run_id}")
            ok = uow.agent.release_lock(day)
            uow.commit()
            return ok


class ForceUnlockDay(UseCase):
    """Operator escape hatch (``victus agent unlock``): drop a lock regardless of holder."""

    def execute(self, day: date) -> bool:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            ok = uow.agent.release_lock(day)
            uow.audit.record("agent.lock.force_release", "agent_lock", day.isoformat(), None)
            uow.commit()
            return ok


class RecordAgentSession(UseCase):
    """One row per (run, day) model conversation; totals roll up into the run (R49)."""

    def execute(
        self,
        run_id: str,
        day: date,
        *,
        model: str | None,
        prompt_version: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        outcome: str,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> dto.AgentSessionView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            run = _run_or_404(uow, run_id)
            session = uow.agent.add_session(
                orm.AgentSession(
                    run_id=run.id,
                    date=day,
                    model=model,
                    prompt_version=prompt_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    outcome=outcome[:32],
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            run.input_tokens += input_tokens
            run.output_tokens += output_tokens
            run.cost_usd += cost_usd
            view = _session_view(session)
            uow.commit()
            return view


class FinishAgentRun(UseCase):
    """Close a run, store the summary, release every lock it still holds."""

    def execute(
        self,
        run_id: str,
        *,
        status: str = RunStatus.FINISHED.value,
        summary_md: str | None = None,
        error: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> dto.AgentRunView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        if status not in FINAL_STATUSES:
            raise ValidationFailed(f"'{status}' is not a final run status")
        with self._uow() as uow:
            run = _run_or_404(uow, run_id)
            if run.status in FINAL_STATUSES:
                return run_view(run, uow.agent.sessions_for(run.id))
            run.status = status
            run.finished_at = now()
            run.summary_md = summary_md
            run.error = error
            if input_tokens is not None:
                run.input_tokens = input_tokens
            if output_tokens is not None:
                run.output_tokens = output_tokens
            if cost_usd is not None:
                run.cost_usd = cost_usd
            released = uow.agent.release_locks(run.id)
            uow.audit.record(
                "agent.run.finish",
                "agent_run",
                run.id,
                {"status": status, "released_locks": released, "cost_usd": run.cost_usd},
            )
            uow.flush()
            view = run_view(run, uow.agent.sessions_for(run.id))
            uow.commit()
            return view


class CancelAgentRun(UseCase):
    def execute(self, run_id: str) -> dto.AgentRunView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        with self._uow() as uow:
            run = _run_or_404(uow, run_id)
            if run.status not in ACTIVE_STATUSES:
                raise Conflict(f"agent run {run_id} is already {run.status}")
            run.status = RunStatus.CANCELLED.value
            run.finished_at = now()
            uow.agent.release_locks(run.id)
            uow.audit.record("agent.run.cancel", "agent_run", run.id, None)
            uow.flush()
            view = run_view(run, uow.agent.sessions_for(run.id))
            uow.commit()
            return view


class ListAgentRuns(UseCase):
    def execute(self, *, limit: int = 50, status: str | None = None) -> list[dto.AgentRunView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.agent.list_runs_by_status(status) if status else uow.agent.list_runs(limit)
            return [run_view(r) for r in list(rows)[:limit]]


class GetAgentRun(UseCase):
    def execute(self, run_id: str) -> dto.AgentRunView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            run = _run_or_404(uow, run_id)
            return run_view(run, uow.agent.sessions_for(run.id))


class ListAgentLocks(UseCase):
    def execute(self) -> list[dto.AgentLockView]:
        self.ctx.require(SCOPE_READ)
        ts = now()
        with self._uow() as uow:
            return [_lock_view(lk) for lk in uow.agent.locks() if lk.locked_until > ts]


# ── day context (what one session sees) ─────────────────────────────────────


class GetDayContext(UseCase):
    """The day thread for a drafting session: current day view, messages, open captures."""

    def execute(self, day: date, *, include_processed: bool = False) -> dto.DayContextView:
        self.ctx.require(SCOPE_READ)
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            d = uow.day_logs.get_by_date(day)
            view = build_day_view(uow, d) if d is not None else None
            thread = GetDayThread(self.uow_factory, self.ctx).execute(day)
            wanted = (
                None
                if include_processed
                else {
                    CaptureStatus.NEW.value,
                    CaptureStatus.IN_PROGRESS.value,
                    CaptureStatus.ASSIGNED.value,
                }
            )
            caps = [
                capture_view(
                    c, uow.captures.transcripts_for(c.id), uow.captures.attachments_of(c.id)
                )
                for c in uow.captures.list(target_date=day)
                if c.product_id is None and (wanted is None or c.status in wanted)
            ]
            holder = uow.agent.lock_holder(day, now())
            return dto.DayContextView(
                date=day,
                day=view,
                thread=thread,
                captures=caps,
                locked_by_run_id=holder.run_id if holder else None,
            )


class GetRecentlyLogged(UseCase):
    """The person's habits around a day: every consumable logged within ``days`` days of
    it — catalogue products, recipe batches and one-offs alike — most frequent first.

    A drafting session gets this as data (#78): ADR 0009 keeps one day's *context* out of
    another's session, not the knowledge that the same cheese was logged three days ago.
    """

    def execute(self, day: date, *, days: int = 14, limit: int = 60) -> dto.RecentlyLogged:
        self.ctx.require(SCOPE_READ)
        start = day - dt.timedelta(days=days)
        end = day + dt.timedelta(days=days + 1)
        with self._uow() as uow:
            rows = [r for r in uow.day_logs.logged_between(start, end) if _as_date(r) != day]
        groups: dict[int, list[Any]] = {}
        for r in rows:
            groups.setdefault(int(r["consumable_id"]), []).append(r)
        items = [_recent_item(cid, entries) for cid, entries in groups.items()]
        items.sort(key=lambda i: (-i.times, -i.last_date.toordinal(), i.name))
        return dto.RecentlyLogged(start=start, end=end, items=items[:limit])


def _as_date(row: Any) -> date:
    value = row["date"]
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _recent_item(consumable_id: int, rows: list[Any]) -> dto.RecentlyLoggedItem:
    """Rows are newest first; the usual amount is the most frequent one, the newest on a tie."""
    counts: dict[tuple[float | None, str | None], int] = {}
    for r in rows:
        key = (float(r["amount"]) if r["amount"] is not None else None, r["unit_code"])
        counts[key] = counts.get(key, 0) + 1
    usual = max(counts, key=lambda k: counts[k])  # dicts keep insertion order: newest wins ties
    usual_row = next(
        r
        for r in rows
        if (float(r["amount"]) if r["amount"] is not None else None, r["unit_code"]) == usual
    )
    first = rows[0]
    return dto.RecentlyLoggedItem(
        consumable_id=consumable_id,
        kind=str(first["kind"]),
        name=str(first["name"]),
        times=len(rows),
        days=len({_as_date(r) for r in rows}),
        last_date=max(_as_date(r) for r in rows),
        usual_amount=usual[0],
        usual_unit_code=str(usual[1]) if usual[1] else None,
        usual_base_amount=float(usual_row["base_amount"]),
        base_unit=str(usual_row["base_unit"]),
    )


def recently_logged_markdown(view: dto.RecentlyLogged) -> str:
    """The session prompt's "recently logged" block: one compact line per consumable."""
    if not view.items:
        return ""
    lines = [
        f"## Recently logged ({view.start.isoformat()} – "
        f"{(view.end - dt.timedelta(days=1)).isoformat()}, this day left out)",
        "",
        "What the person logged around this day, most frequent first: `[id] name (kind) — "
        "times on days, last date, usual amount`. Prefer these over a new estimate when one "
        "fits; an `ad_hoc` entry is a one-off logged before (see the rules on reusing it).",
        "",
    ]
    for i in view.items:
        if i.usual_amount is not None and i.usual_unit_code:
            amount = f"{i.usual_amount:g} {i.usual_unit_code}"
            if i.usual_unit_code != i.base_unit:
                amount += f" ({i.usual_base_amount:g} {i.base_unit})"
        else:
            amount = f"{i.usual_base_amount:g} {i.base_unit}"
        lines.append(
            f"- [{i.consumable_id}] {i.name} ({i.kind}) — {i.times}× on {i.days} day(s), "
            f"last {i.last_date.isoformat()}, usually {amount}"
        )
    return "\n".join(lines)


class AddAgentMessage(UseCase):
    """Agent-side thread entry: summary, question or note for a day (ADR 0010).

    ``summary`` is the day's verdict and there is exactly one: a later run corrects it
    instead of stacking a second opinion under the first, which is also what the day page
    shows above the meals. Notes and questions accumulate, because each is about a
    different thing.
    """

    def execute(self, run_id: str, day: date, kind: str, content: str) -> dto.DayMessageView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        if kind not in {k.value for k in MessageKind}:
            raise ValidationFailed(f"unknown message kind '{kind}'")
        if not content.strip():
            raise ValidationFailed("message content is required")
        with self._uow() as uow:
            _run_or_404(uow, run_id)
            if kind == MessageKind.SUMMARY.value:
                uow.day_messages.remove_kind(day, kind)
            m = uow.day_messages.add(
                orm.DayMessage(
                    tenant_id=self.ctx.tenant_id,
                    date=day,
                    role=MessageRole.AGENT.value,
                    kind=kind,
                    content=content.strip(),
                    run_id=run_id,
                )
            )
            view = dto.DayMessageView(
                id=str(m.id),
                role=m.role,
                kind=m.kind,
                content=m.content,
                created_at=m.created_at,
                processing_state=None,
            )
            uow.commit()
            return view


# ── drafts ───────────────────────────────────────────────────────────────────


def validate_draft(draft: dict[str, Any]) -> None:
    """Validate against ``schemas/agent-draft.schema.json``; raise ValidationFailed."""
    schema = load_schema("agent-draft")
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    )
    errors = sorted(validator.iter_errors(draft), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValidationFailed(
            "draft does not match agent-draft.schema.json",
            errors=[
                {"path": "/".join(str(p) for p in e.absolute_path), "message": e.message}
                for e in errors[:20]
            ],
        )


def _find_meal(d: orm.DayLog, name: str) -> orm.Meal | None:
    key = name.strip().lower()
    return next((m for m in d.meals if (m.name or "").strip().lower() == key), None)


def _parse_time(value: str | None) -> dt.time | None:
    if not value:
        return None
    hh, mm = value.split(":")
    return dt.time(int(hh), int(mm))


class CreateDraft(UseCase):
    """Write one day's draft from the agent's structured output (R37).

    Requires a live lock held by ``run_id`` for the day; creates the day log in
    ``draft`` status when it is new, otherwise adds draft line items to the
    existing day. Captures are moved to ``assigned``; notes and open questions
    become thread messages.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        ctx: TenantContext,
        *,
        match_threshold: float = 0.62,
    ) -> None:
        super().__init__(uow_factory, ctx)
        self.match_threshold = match_threshold

    def execute(self, draft: dict[str, Any]) -> dto.DraftCreateView:
        self.ctx.require(SCOPE_AGENT_WRITE)
        validate_draft(draft)
        run_id = str(draft["run_id"])
        day = date.fromisoformat(str(draft["date"]))
        ts = now()
        with self._uow() as uow:
            run = _running_run(uow, run_id)
            holder = uow.agent.lock_holder(day, ts)
            if holder is None:
                raise LockHeldByOtherRun(
                    f"no live lock for {day.isoformat()}; start a run or acquire the day first"
                )
            if holder.run_id != run.id:
                raise LockHeldByOtherRun(
                    f"{day.isoformat()} is locked by {holder.runner} run {holder.run_id}"
                )
            d = uow.day_logs.get_by_date(day)
            if d is None:
                d = uow.day_logs.add(
                    orm.DayLog(
                        tenant_id=self.ctx.tenant_id,
                        date=day,
                        weekday=weekday_name(day),
                        reliable=None,
                        status=DayStatus.DRAFT.value,
                        created_by_kind="agent",
                        agent_run_id=run.id,
                        generated_at=ts,
                    )
                )
            elif d.status == DayStatus.CLOSED.value:
                raise Conflict(f"{day.isoformat()} is closed; reopen it before drafting")
            training = draft.get("training")
            if training and not d.training_type:
                d.training_type = TrainingType(training).value

            created = 0
            ad_hoc = 0
            proposed: list[str] = []
            for meal_in in draft["meals"]:
                meal = _find_meal(d, meal_in["name"])
                if meal is None:
                    position = (max((m.position for m in d.meals), default=0)) + 1
                    meal = uow.day_logs.add_meal(
                        orm.Meal(
                            day_log_id=d.id,
                            position=position,
                            name=meal_in["name"],
                            time=_parse_time(meal_in.get("time")),
                        )
                    )
                    # no branch: d.meals was loaded by _find_meal, and a meal built from
                    # day_log_id alone never joins it, so this guard is always true
                    if meal not in d.meals:  # pragma: no branch
                        d.meals.append(meal)
                for item in meal_in["line_items"]:
                    li, is_ad_hoc = self._line_item(uow, meal, item)
                    created += 1
                    ad_hoc += int(is_ad_hoc)
                    filed = self._propose_returning_one_off(uow, li.consumable_id, run.id)
                    if filed:
                        proposed.append(filed)

            assigned = 0
            for cid in draft.get("source_captures", []):
                cap = uow.captures.get(str(cid))
                if cap is None:
                    continue
                if cap.status in (CaptureStatus.NEW.value, CaptureStatus.IN_PROGRESS.value):
                    cap.status = CaptureStatus.ASSIGNED.value
                    assigned += 1
                cap.agent_run_id = run.id
                if cap.target_date is None:
                    cap.target_date = day

            questions = 0
            for note in draft.get("notes", []) or []:
                uow.day_messages.add(
                    orm.DayMessage(
                        tenant_id=self.ctx.tenant_id,
                        date=day,
                        role=MessageRole.AGENT.value,
                        kind=MessageKind.NOTE.value,
                        content=str(note),
                        run_id=run.id,
                    )
                )
            for q in draft.get("open_questions", []) or []:
                uow.day_messages.add(
                    orm.DayMessage(
                        tenant_id=self.ctx.tenant_id,
                        date=day,
                        role=MessageRole.AGENT.value,
                        kind=MessageKind.QUESTION.value,
                        content=str(q),
                        run_id=run.id,
                    )
                )
                questions += 1

            if draft.get("prompt_version") and not run.prompt_version:
                run.prompt_version = str(draft["prompt_version"])
            uow.audit.record(
                "draft.create",
                "day_log",
                str(d.id),
                {
                    "run_id": run.id,
                    "items": created,
                    "ad_hoc": ad_hoc,
                    "captures": assigned,
                    "proposed": proposed,
                },
            )
            uow.flush()
            view = build_day_view(uow, d)
            result = dto.DraftCreateView(
                date=day,
                day=view,
                created_items=created,
                created_ad_hoc=ad_hoc,
                captures_assigned=assigned,
                questions=questions,
                markdown=draft_markdown(view),
                proposed_products=proposed,
            )
            uow.commit()
            return result

    def _line_item(
        self, uow: UnitOfWork, meal: orm.Meal, item: dict[str, Any]
    ) -> tuple[orm.LineItem, bool]:
        chosen = item.get("chosen_consumable_id")
        is_ad_hoc = False
        if chosen is not None:
            consumable = uow.products.get_consumable(int(chosen))
            if consumable is None:
                raise NotFound(f"consumable {chosen} not found")
        else:
            nutrition = item.get("one_off_nutrition_per_100")
            if not nutrition or nutrition.get("kcal") is None:
                raise ValidationFailed(
                    f"'{item['raw_text']}': no product chosen and no one_off_nutrition_per_100"
                )
            name = str(item.get("one_off_name") or "").strip() or one_off_name(item["raw_text"])
            unit = "ml" if item.get("unit_code") == "ml" else "g"
            again = uow.products.ad_hoc_named(name)
            earlier = uow.products.get_ad_hoc_item(again.id) if again is not None else None
            if again is not None and earlier is not None and earlier.reference_unit == unit:
                # the same food estimated before: log it against that one-off, so both days
                # count the same values and a promotion keeps both items (#78)
                return self._add_line_item(uow, meal, item, again, is_ad_hoc=True), True
            ad = uow.products.add_ad_hoc_item(
                name[:300],
                reference_amount=100.0,
                reference_unit=unit,
                kcal=nutrition.get("kcal"),
                protein=nutrition.get("protein"),
                carbs=nutrition.get("carbs"),
                fat=nutrition.get("fat"),
                fiber=nutrition.get("fiber"),
                salt=nutrition.get("salt"),
                origin_text=(nutrition.get("source") or item.get("rationale") or "")[:500],
            )
            consumable = uow.products.get_consumable(ad.id)
            assert consumable is not None
            is_ad_hoc = True
        return self._add_line_item(uow, meal, item, consumable, is_ad_hoc=is_ad_hoc), is_ad_hoc

    def _add_line_item(
        self,
        uow: UnitOfWork,
        meal: orm.Meal,
        item: dict[str, Any],
        consumable: orm.Consumable,
        *,
        is_ad_hoc: bool,
    ) -> orm.LineItem:
        inp = LineItemInput(
            consumable_id=consumable.id,
            amount=float(item["quantity"]),
            unit_code=str(item["unit_code"]),
            estimated=bool(item.get("estimated", False)),
            amount_estimated=bool(item.get("quantity_estimated", False)),
            raw_text=item.get("raw_text"),
        )
        try:
            base, base_unit, portion_id = resolve_base(uow, consumable, inp)
        except ValidationFailed:
            # count unit without a portion: accept the agent's frozen base quantity, which
            # the prompt asks for in grams even when the product is stated per ml (R75)
            if item.get("base_quantity") is None:
                raise
            base, base_unit = in_reference_unit(uow, consumable, float(item["base_quantity"]), "g")
            portion_id = None
        position = (max((li.position for li in meal.line_items), default=0)) + 1
        li = uow.day_logs.add_line_item(
            orm.LineItem(
                meal_id=meal.id,
                position=position,
                consumable_id=consumable.id,
                portion_id=portion_id,
                unit_code=inp.unit_code,
                amount=inp.amount,
                base_amount=base,
                base_unit=base_unit,
                amount_estimated=inp.amount_estimated,
                estimated=inp.estimated or is_ad_hoc,
                raw_text=inp.raw_text,
                origin="agent",
                is_draft=True,
                confidence=float(item["confidence"]),
                rationale=str(item.get("rationale") or "")[:2000] or None,
                source_capture_id=str(item["source_capture_id"]),
                source_kind=str(item["source_kind"]),
                alternatives=[
                    {
                        "consumable_id": c["consumable_id"],
                        "name": c["name"],
                        "score": c["score"],
                        "tier": c["tier"],
                    }
                    for c in item.get("candidates", [])[:3]
                ],
            )
        )
        # no branch: meal.line_items was loaded by the max() above, and an item built from
        # meal_id alone never joins it, so this guard is always true
        if li not in meal.line_items:  # pragma: no branch
            # keep the in-memory collection current so the returned day view sees the item
            meal.line_items.append(li)
        return li

    def _propose_returning_one_off(
        self, uow: UnitOfWork, consumable_id: int, run_id: str
    ) -> str | None:
        """File a one-off that is logged a second time as a ``new`` product proposal.

        A one-off estimated once used to be estimated again every time, because search
        never saw it and nothing asked the person to keep it. From its second line item on
        it is a food the person eats, so it goes to the review list once — approving
        promotes it in place, keeping its id and every item logged against it (R81). Any
        proposal the one-off already has (pending, approved or rejected) means a person was
        asked already, and a product of that name means approving could only collide.
        Returns the name filed, or ``None``.
        """
        item = uow.products.get_ad_hoc_item(consumable_id)
        consumable = uow.products.get_consumable(consumable_id)
        if item is None or consumable is None:
            return None
        if uow.proposals.list(consumable_id=consumable_id, limit=1):
            return None
        times = uow.day_logs.usage_count(consumable_id)
        if times < 2 or uow.products.by_name(consumable.name) is not None:
            return None
        values = {
            "name": consumable.name,
            "reference_amount": item.reference_amount,
            "reference_unit": item.reference_unit,
            **{
                k: getattr(item, k)
                for k in ("kcal", "protein", "carbs", "fat", "fiber", "salt")
                if getattr(item, k) is not None
            },
        }
        source = (item.origin_text or "")[:300] or None
        if source:
            values["source"] = source
        pr = uow.proposals.add(
            orm.ProductProposal(
                tenant_id=self.ctx.tenant_id,
                product_id=None,
                kind=NEW,
                consumable_id=consumable_id,
                run_id=run_id,
                changes=values,
                rationale=(
                    f"Logged as a one-off {times} times; filed so it can be approved once "
                    "and found from then on."
                ),
                source=source,
                status=PENDING,
                created_by=author_of(self.ctx),
            )
        )
        uow.audit.record(
            "product.propose_new",
            "consumable",
            str(consumable_id),
            {"proposal": pr.id, "name": consumable.name, "returning_one_off": True},
        )
        return consumable.name
