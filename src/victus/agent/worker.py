"""The worker process: a queue consumer with an optional cron trigger (SPEC R50).

``victus worker`` polls every ``agent.poll_seconds`` for queued runs across all
active tenants and processes them oldest first. When ``agent.enabled`` and
``agent.cron`` are set, a ``historical`` run is queued per tenant whenever the
cron expression matches — that is the only thing the schedule does; the
"Process now" button and MCP create the same queued rows.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import RunNotActive
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.backup.schedule import CronSpec
from victus.config.server import ServerConfig
from victus.domain.values import AgentMode, RunStatus
from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.mcp.server import make_tool_context
from victus.mcp.tools import ToolContext

from .model import AnthropicModelClient, ModelClient
from .runner import RunOutcome, RunProcessor, worker_context

log = logging.getLogger("victus.worker")

DEFAULT_HEARTBEAT = "/tmp/victus-worker.alive"

ModelFactory = Callable[[ServerConfig], ModelClient | None]


def default_model_factory(cfg: ServerConfig) -> ModelClient | None:
    key = cfg.providers.anthropic_api_key
    if key is None:
        return None
    return AnthropicModelClient(
        key.get_secret_value(),
        model=cfg.agent.model,
        effort=cfg.agent.effort,
        max_tokens=cfg.agent.max_tokens,
        fallbacks=cfg.agent.fallbacks,
    )


class Worker:
    def __init__(
        self,
        config: ServerConfig,
        session_factory: sessionmaker[Session],
        *,
        model_factory: ModelFactory = default_model_factory,
        blobs: Any = None,
        transcription: Any = None,
        heartbeat_path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.cfg = config
        self.session_factory = session_factory
        self.model_factory = model_factory
        self.blobs = blobs
        self.transcription = transcription
        self.heartbeat = Path(
            heartbeat_path or os.environ.get("VICTUS_WORKER_HEARTBEAT", DEFAULT_HEARTBEAT)
        )
        self._now = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._cron = CronSpec.parse(config.agent.cron) if config.agent.cron else None
        self._last_cron_minute: datetime | None = None
        self._model: ModelClient | None = None
        self._model_resolved = False

    # -- infrastructure --

    def _tenants(self) -> list[orm.Tenant]:
        with self.session_factory() as s:
            return list(s.scalars(select(orm.Tenant).where(orm.Tenant.active.is_(True))).all())

    def _tool_context(self, tenant_id: str) -> ToolContext:
        return make_tool_context(
            self.session_factory,
            worker_context(tenant_id),
            self.cfg,
            blobs=self.blobs,
            transcription=self.transcription,
        )

    def _model_client(self) -> ModelClient | None:
        if not self._model_resolved:
            self._model = self.model_factory(self.cfg)
            self._model_resolved = True
        return self._model

    def touch_heartbeat(self) -> None:
        try:
            self.heartbeat.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat.touch()
        except OSError as exc:  # pragma: no cover - read-only filesystems
            log.debug("heartbeat not written: %s", exc)

    # -- work --

    def queue_scheduled_runs(self, now: datetime | None = None) -> int:
        """Queue one ``historical`` run per tenant when the cron matches this minute."""
        if not (self.cfg.agent.enabled and self._cron):
            return 0
        ts = (now or self._now()).replace(second=0, microsecond=0)
        if self._last_cron_minute == ts or not self._cron.matches(ts):
            return 0
        self._last_cron_minute = ts
        queued = 0
        for tenant in self._tenants():
            ctx = worker_context(tenant.id)
            with SqlAlchemyUnitOfWork(self.session_factory, ctx) as uow:
                if any(
                    r.mode == AgentMode.HISTORICAL.value and r.runner == "worker"
                    for r in uow.agent.queued_runs()
                ):
                    continue
            agent_uc.QueueAgentRun(self._factory(), ctx).execute(AgentMode.HISTORICAL.value)
            queued += 1
        return queued

    def _factory(self) -> Callable[[TenantContext], SqlAlchemyUnitOfWork]:
        def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(self.session_factory, ctx)

        return make

    def queued_runs(self) -> list[tuple[str, str]]:
        """(tenant_id, run_id) for every queued run, oldest first across tenants."""
        with self.session_factory() as s:
            rows = s.execute(
                select(orm.AgentRun.tenant_id, orm.AgentRun.id)
                .where(orm.AgentRun.status == RunStatus.QUEUED.value)
                .order_by(orm.AgentRun.created_at)
            ).all()
        return [(str(t), str(r)) for t, r in rows]

    def process_run(self, tenant_id: str, run_id: str) -> RunOutcome | None:
        tc = self._tool_context(tenant_id)
        processor = RunProcessor(tc, self._model_client(), self.cfg)
        try:
            outcome = processor.process(run_id)
        except RunNotActive:
            log.info("run %s was taken by another worker", run_id)
            return None
        except Exception as exc:
            log.exception("run %s failed", run_id)
            try:
                agent_uc.FinishAgentRun(tc.uow_factory, tc.ctx).execute(
                    run_id, status=RunStatus.FAILED.value, error=str(exc)[:2000]
                )
            except Exception:
                log.exception("run %s could not be marked failed", run_id)
            return None
        log.info(
            "run %s finished: %s (%d days, %.2f USD)",
            run_id,
            outcome.run.status,
            len(outcome.days),
            outcome.run.cost_usd,
        )
        return outcome

    def run_once(self) -> list[RunOutcome]:
        """One tick: heartbeat, cron, then every queued run. Returns the outcomes."""
        self.touch_heartbeat()
        self.queue_scheduled_runs()
        outcomes: list[RunOutcome] = []
        for tenant_id, run_id in self.queued_runs():
            if self._stop.is_set():
                break
            outcome = self.process_run(tenant_id, run_id)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def stop(self) -> None:
        self._stop.set()

    def install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: FrameType | None) -> None:
            log.info("signal %s: stopping after the current run", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):  # not the main thread
                signal.signal(sig, handler)

    def run_forever(self) -> None:
        self.install_signal_handlers()
        log.info(
            "worker started (poll %ss, cron %s, model %s)",
            self.cfg.agent.poll_seconds,
            self.cfg.agent.cron if self.cfg.agent.enabled else "disabled",
            self.cfg.agent.model,
        )
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("worker tick failed")
            self._stop.wait(max(1, self.cfg.agent.poll_seconds))
        log.info("worker stopped")
