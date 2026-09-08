"""The in-house runner: one fresh model conversation per day (ADR 0009, SPEC R49).

``RunProcessor.process(run_id)`` takes a queued run through ``BeginAgentRun``,
drafts every locked day in its own ``DayDrafter`` session, assembles the run
summary (``prompts/summary.md`` documents the shape) and closes the run with
``FinishAgentRun``. The model only ever sees the tools in ``WORKER_TOOLS``; it
cannot approve.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import cache
from importlib import resources
from typing import Any, cast

from victus.application import dto
from victus.application.errors import ApplicationError, ExternalServiceError
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import products as product_uc
from victus.application.use_cases import rules as rules_uc
from victus.config.server import ServerConfig
from victus.domain.values import CaptureKind, CaptureStatus, MessageKind, Period, RunStatus
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.reports.sqlalchemy_source import SqlAlchemyReportDataSource
from victus.mcp.tools import (
    WORKER_TOOLS,
    ImageResult,
    ToolContext,
    ToolError,
    anthropic_tool_definitions,
    dispatch,
    jsonable,
    result_text,
    tools_for,
)
from victus.reports.engine import ReportEngine
from victus.reports.registry import ReportRegistry
from victus.reports.render.markdown import to_markdown

from .budget import Budget
from .model import ModelClient, ModelError, ModelResponse
from .pricing import turn_cost_usd

log = logging.getLogger("victus.agent")

WORKER_SCOPES: frozenset[str] = frozenset(
    {SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE}
)
MAX_IMAGE_EDGE = 1024


# ── prompts ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Prompts:
    system: str
    capture_to_draft: str
    product_capture: str
    summary: str
    version: str


@cache
def load_prompts() -> Prompts:
    package = resources.files("victus.agent.prompts")
    texts = {
        name: (package / f"{name}.md").read_text(encoding="utf-8")
        for name in ("system", "capture_to_draft", "product_capture", "summary")
    }
    digest = hashlib.sha256("\n".join(texts[n] for n in sorted(texts)).encode("utf-8"))
    return Prompts(
        system=texts["system"],
        capture_to_draft=texts["capture_to_draft"],
        product_capture=texts["product_capture"],
        summary=texts["summary"],
        version=digest.hexdigest()[:12],
    )


# ── outcomes ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class DayOutcome:
    date: date
    outcome: str  # drafted | no_draft | refused | budget_exceeded | failed | stuck
    draft: dict[str, Any] | None = None  # jsonable DraftCreateView from the draft_create tool
    markdown: str = ""
    error: str | None = None
    questions: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0


@dataclass(slots=True)
class RunOutcome:
    run: dto.AgentRunView
    days: list[DayOutcome]
    skipped: dict[date, str]
    summary_md: str


# ── helpers ─────────────────────────────────────────────────────────────────


def worker_context(tenant_id: str) -> TenantContext:
    return TenantContext(tenant_id=tenant_id, scopes=WORKER_SCOPES)


def _downscale(data: bytes, mime: str) -> tuple[bytes, str]:
    """Shrink an image to at most 1024 px on the long edge (JPEG); pass through on failure."""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - optional dependency
        return data, mime
    try:
        with Image.open(io.BytesIO(data)) as raw:
            img: Any = ImageOps.exif_transpose(raw) or raw
            if max(img.size) > MAX_IMAGE_EDGE:
                img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        log.warning("image downscale failed (%s); sending original", exc)
        return data, mime


def context_json(view: dto.DayContextView) -> str:
    data = cast(dict[str, Any], jsonable(view))
    return json.dumps(data, ensure_ascii=False, indent=1, default=str)


def tenant_rules(tc: ToolContext, scope: str) -> str:
    """The user's own instructions, as Markdown for the session prompt (R61)."""
    try:
        rows = rules_uc.ListRules(tc.uow_factory, tc.ctx).execute(scope=scope, enabled_only=True)
    except ApplicationError:
        return ""
    return rules_uc.rules_markdown(rows)


def tenant_language(tc: ToolContext) -> str:
    with tc.uow_factory(tc.ctx) as uow:
        language, _ = capture_uc.transcription_settings(uow)
    return language or "en"


# ── one day, one session ────────────────────────────────────────────────────


class DayDrafter:
    def __init__(
        self,
        tool_ctx: ToolContext,
        model: ModelClient,
        config: ServerConfig,
        budget: Budget,
        *,
        clock: Any = None,
    ) -> None:
        self.tc = tool_ctx
        self.model = model
        self.cfg = config
        self.budget = budget
        self.prompts = load_prompts()
        self._now = clock or (lambda: datetime.now(UTC))

    # -- context assembly --

    def _transcribe_pending(self, view: dto.DayContextView) -> tuple[list[str], bool]:
        """Transcribe audio captures that have no transcript yet; (notes, anything changed)."""
        notes: list[str] = []
        changed = False
        if self.tc.transcription is None or self.tc.blobs is None:
            return notes, changed
        for cap in view.captures:
            if cap.kind == CaptureKind.AUDIO.value and cap.transcript is None:
                changed = True
                try:
                    capture_uc.TranscribeCapture(
                        self.tc.uow_factory, self.tc.ctx, self.tc.blobs, self.tc.transcription
                    ).execute(cap.id)
                except ExternalServiceError as exc:
                    notes.append(f"capture {cap.id}: transcription failed ({exc.detail})")
        return notes, changed

    def _image_blocks(self, view: dto.DayContextView) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        if self.tc.blobs is None:
            return blocks
        images = [c for c in view.captures if c.kind == CaptureKind.IMAGE.value and c.attachment_id]
        allowed = self.budget.take_images(len(images))
        for cap in images[:allowed]:
            assert cap.attachment_id is not None
            att = capture_uc.GetAttachment(self.tc.uow_factory, self.tc.ctx, self.tc.blobs).execute(
                cap.attachment_id
            )
            data, mime = _downscale(att.data, att.mime)
            blocks.append({"type": "text", "text": f"Image for capture {cap.id}:"})
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
        if allowed < len(images):
            blocks.append(
                {
                    "type": "text",
                    "text": f"{len(images) - allowed} image(s) omitted: image budget exhausted.",
                }
            )
        return blocks

    def _first_message(self, run_id: str, day: date) -> tuple[list[dict[str, Any]], list[str]]:
        view = agent_uc.GetDayContext(self.tc.uow_factory, self.tc.ctx).execute(day)
        notes, changed = self._transcribe_pending(view)
        if changed:
            view = agent_uc.GetDayContext(self.tc.uow_factory, self.tc.ctx).execute(day)
        task = self.prompts.capture_to_draft.format(
            date=day.isoformat(), run_id=run_id, language=tenant_language(self.tc)
        )
        content: list[dict[str, Any]] = [
            {"type": "text", "text": task},
            {"type": "text", "text": "## Day context (JSON)\n" + context_json(view)},
        ]
        rules = tenant_rules(self.tc, "days")
        if rules:
            content.append({"type": "text", "text": rules})
        if notes:
            content.append({"type": "text", "text": "Notes: " + "; ".join(notes)})
        content.extend(self._image_blocks(view))
        return content, [c.id for c in view.captures]

    # -- tool execution --

    def _tool_results(self, response: ModelResponse, outcome: DayOutcome) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for use in response.tool_uses:
            try:
                result = dispatch(self.tc, use.name, use.input)
            except ToolError as exc:
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": f"{exc.code}: {exc.message}",
                        "is_error": True,
                    }
                )
                continue
            if use.name == "draft_create" and isinstance(result, dict):
                outcome.draft = result
                outcome.markdown = str(result.get("markdown", ""))
                outcome.questions = self._questions_from(use.input)
                outcome.outcome = "drafted"
            if use.name == "product_propose" and isinstance(result, dict):
                outcome.draft = result
                outcome.outcome = "proposed"
            if isinstance(result, ImageResult):
                content: Any = [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": result.mime,
                            "data": result.data_b64,
                        },
                    },
                    {"type": "text", "text": result.text},
                ]
            else:
                content = result_text(result)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": content})
        return results

    @staticmethod
    def _questions_from(draft_input: dict[str, Any]) -> list[str]:
        return [str(q) for q in (draft_input.get("open_questions") or [])]

    # -- the session --

    def run_day(self, run_id: str, day: date) -> DayOutcome:
        outcome = DayOutcome(date=day, outcome="no_draft")
        started = self._now()
        tools = anthropic_tool_definitions(tools_for(self.tc.ctx, WORKER_TOOLS))
        try:
            content, _capture_ids = self._first_message(run_id, day)
        except ApplicationError as exc:
            outcome.outcome, outcome.error = "failed", exc.detail
            self._record(run_id, outcome, started)
            return outcome
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        self._converse(run_id, day, messages, outcome, tools, success="drafted")
        self._record(run_id, outcome, started)
        if outcome.outcome == "drafted" and outcome.markdown:
            agent_uc.AddAgentMessage(self.tc.uow_factory, self.tc.ctx).execute(
                run_id, day, MessageKind.SUMMARY.value, outcome.markdown
            )
        return outcome

    def _converse(
        self,
        run_id: str,
        day: date | None,
        messages: list[dict[str, Any]],
        outcome: DayOutcome,
        tools: list[dict[str, Any]],
        *,
        success: str,
    ) -> None:
        """The model loop shared by day drafting and product review."""
        for _turn in range(self.cfg.agent.max_turns_per_day):
            try:
                response = self.model.create(
                    system=self.prompts.system, messages=messages, tools=tools
                )
            except ModelError as exc:
                outcome.outcome, outcome.error = "failed", str(exc)
                break
            outcome.turns += 1
            cost = turn_cost_usd(
                self.cfg.agent, response.model, response.input_tokens, response.output_tokens
            )
            outcome.input_tokens += response.input_tokens
            outcome.output_tokens += response.output_tokens
            outcome.cost_usd += cost
            self.budget.charge(
                input_tokens=response.input_tokens, output_tokens=response.output_tokens, usd=cost
            )
            messages.append({"role": "assistant", "content": response.content_params})
            if response.stop_reason == "refusal":
                outcome.outcome = "refused"
                outcome.error = (response.stop_details or {}).get("explanation") or "model refused"
                break
            if response.tool_uses:
                results = self._tool_results(response, outcome)
                messages.append({"role": "user", "content": results})
                if day is not None:
                    agent_uc.ExtendDayLock(self.tc.uow_factory, self.tc.ctx).execute(
                        run_id, day, lock_ttl_minutes=self.cfg.agent.lock_ttl_minutes
                    )
            reason = self.budget.exceeded
            if reason:
                if outcome.outcome != success:
                    outcome.outcome = "budget_exceeded"
                outcome.error = f"budget exhausted: {reason}"
                break
            if response.stop_reason != "tool_use":
                break
        else:
            if outcome.outcome != success:
                outcome.outcome = "stuck"
                outcome.error = f"no result after {self.cfg.agent.max_turns_per_day} turns"

    # -- product captures (label photos, corrections): one short session each --

    def run_product_capture(self, run_id: str, cap: dto.CaptureView) -> DayOutcome:
        """Read one product capture and propose corrected values (R52)."""
        outcome = DayOutcome(date=cap.captured_at.date(), outcome="product_skipped")
        started = self._now()
        tools = anthropic_tool_definitions(tools_for(self.tc.ctx, WORKER_TOOLS))
        try:
            assert cap.product_id is not None
            product = product_uc.GetProduct(self.tc.uow_factory, self.tc.ctx).execute(
                cap.product_id
            )
            fresh = cap
            if (
                cap.kind == CaptureKind.AUDIO.value
                and cap.transcript is None
                and self.tc.transcription is not None
                and self.tc.blobs is not None
            ):
                fresh = capture_uc.TranscribeCapture(
                    self.tc.uow_factory, self.tc.ctx, self.tc.blobs, self.tc.transcription
                ).execute(cap.id)
            content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": self.prompts.product_capture.format(
                        run_id=run_id, capture_id=cap.id, language=tenant_language(self.tc)
                    ),
                },
                {"type": "text", "text": "## Product (JSON)\n" + json.dumps(jsonable(product))},
                {"type": "text", "text": "## Capture (JSON)\n" + json.dumps(jsonable(fresh))},
            ]
            product_rules = tenant_rules(self.tc, "products")
            if product_rules:
                content.append({"type": "text", "text": product_rules})
            if fresh.kind == CaptureKind.IMAGE.value and fresh.attachment_id and self.tc.blobs:
                if self.budget.take_images(1):
                    att = capture_uc.GetAttachment(
                        self.tc.uow_factory, self.tc.ctx, self.tc.blobs
                    ).execute(fresh.attachment_id)
                    data, mime = _downscale(att.data, att.mime)
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": base64.b64encode(data).decode("ascii"),
                            },
                        }
                    )
                else:
                    content.append(
                        {"type": "text", "text": "Image omitted: image budget exhausted."}
                    )
        except ApplicationError as exc:
            outcome.outcome, outcome.error = "failed", exc.detail
            self._record(run_id, outcome, started)
            return outcome
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        self._converse(run_id, None, messages, outcome, tools, success="proposed")
        self._record(run_id, outcome, started)
        return outcome

    def _record(self, run_id: str, outcome: DayOutcome, started: datetime) -> None:
        agent_uc.RecordAgentSession(self.tc.uow_factory, self.tc.ctx).execute(
            run_id,
            outcome.date,
            model=self.model.model,
            prompt_version=self.prompts.version,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            cost_usd=outcome.cost_usd,
            outcome=outcome.outcome,
            started_at=started,
            finished_at=self._now(),
        )


# ── the run ─────────────────────────────────────────────────────────────────


class RunProcessor:
    def __init__(
        self, tool_ctx: ToolContext, model: ModelClient | None, config: ServerConfig
    ) -> None:
        self.tc = tool_ctx
        self.model = model
        self.cfg = config

    def process(self, run_id: str) -> RunOutcome:
        prompts = load_prompts()
        begin = agent_uc.BeginAgentRun(self.tc.uow_factory, self.tc.ctx)
        if self.model is None:
            start = begin.execute(run_id=run_id, lock_ttl_minutes=self.cfg.agent.lock_ttl_minutes)
            error = "no model configured: set providers.anthropic_api_key"
            run = agent_uc.FinishAgentRun(self.tc.uow_factory, self.tc.ctx).execute(
                run_id, status=RunStatus.FAILED.value, error=error, summary_md=None
            )
            return RunOutcome(run=run, days=[], skipped=start.skipped_days, summary_md=error)
        start = begin.execute(
            run_id=run_id,
            lock_ttl_minutes=self.cfg.agent.lock_ttl_minutes,
            model=self.model.model,
            prompt_version=prompts.version,
        )
        self.tc.run_id = run_id
        budget = Budget.from_config(self.cfg.agent.budget)
        drafter = DayDrafter(self.tc, self.model, self.cfg, budget)
        outcomes: list[DayOutcome] = []
        skipped = dict(start.skipped_days)
        status = RunStatus.FINISHED.value
        # product captures first: short, independent of any day lock
        product_outcomes: list[DayOutcome] = []
        for cap in capture_uc.ListCaptures(self.tc.uow_factory, self.tc.ctx).execute(
            status=CaptureStatus.NEW.value
        ):
            if cap.product_id is None:
                continue
            if budget.exceeded:
                break
            try:
                product_outcomes.append(drafter.run_product_capture(run_id, cap))
            except Exception as exc:
                log.exception("run %s: product capture %s failed", run_id, cap.id)
                product_outcomes.append(
                    DayOutcome(date=cap.captured_at.date(), outcome="failed", error=str(exc))
                )
        for day in start.locked_days:
            if budget.exceeded:
                skipped[day] = "budget exhausted"
                continue
            try:
                outcomes.append(drafter.run_day(run_id, day))
            except Exception as exc:
                log.exception("run %s: day %s failed", run_id, day)
                outcomes.append(DayOutcome(date=day, outcome="failed", error=str(exc)))
            agent_uc.ReleaseDayLock(self.tc.uow_factory, self.tc.ctx).execute(run_id, day)
        if any(o.outcome == "budget_exceeded" for o in outcomes) or (budget.exceeded and skipped):
            status = RunStatus.BUDGET_EXCEEDED.value
        elif outcomes and all(o.outcome == "failed" for o in outcomes):
            status = RunStatus.FAILED.value
        summary = self.build_summary(run_id, start, outcomes, skipped, budget)
        if product_outcomes:
            n_prop = sum(1 for o in product_outcomes if o.outcome == "proposed")
            lines = [f"### Products · {n_prop} proposal(s) from {len(product_outcomes)} capture(s)"]
            for o in product_outcomes:
                if o.outcome == "proposed" and o.draft:
                    name = o.draft.get("product_name") or o.draft.get("product_id")
                    lines.append(f"- {name}: {o.draft.get('changes')} — approve in the app")
                else:
                    lines.append(f"- {o.outcome.replace('_', ' ')}: {o.error or ''}".rstrip())
            summary = summary.rstrip() + "\n\n" + "\n".join(lines) + "\n"
        errors = [f"{o.date.isoformat()}: {o.error}" for o in outcomes if o.error]
        run = agent_uc.FinishAgentRun(self.tc.uow_factory, self.tc.ctx).execute(
            run_id,
            status=status,
            summary_md=summary,
            error="; ".join(errors) if errors else None,
        )
        return RunOutcome(run=run, days=outcomes, skipped=skipped, summary_md=summary)

    # -- summary (see prompts/summary.md) --

    def _checkup(self) -> str | None:
        try:
            definition = ReportRegistry().get("checkup")
            today = datetime.now(UTC).date()
            period = Period(today - timedelta(days=13), today)
            with self.tc.uow_factory(self.tc.ctx) as uow:
                source = SqlAlchemyReportDataSource(cast(SqlAlchemyUnitOfWork, uow))
                result = ReportEngine(source).render(definition, period, today=today)
            return to_markdown(result)
        except Exception as exc:
            log.warning("checkup for the run summary failed: %s", exc)
            return None

    def build_summary(
        self,
        run_id: str,
        start: dto.RunStartView,
        outcomes: list[DayOutcome],
        skipped: dict[date, str],
        budget: Budget,
    ) -> str:
        days = sorted({*start.locked_days, *skipped})
        first = days[0].isoformat() if days else "–"
        last = days[-1].isoformat() if days else "–"
        n_captures = len(start.run.captures) or sum(
            int((o.draft or {}).get("captures_assigned", 0)) for o in outcomes
        )
        lines = [
            f"## Drafts {first} – {last} (run {run_id[:8]}, {len(days)} days, "
            f"{n_captures} captures, {budget.usd:.2f} USD)",
            "",
        ]
        for o in sorted(outcomes, key=lambda x: x.date):
            if o.outcome == "drafted" and o.markdown:
                lines.append(o.markdown.rstrip())
                for q in o.questions:
                    lines.append(f"- ? {q}")
            else:
                reason = o.error or o.outcome.replace("_", " ")
                lines.append(f"### {o.date.isoformat()} · {o.outcome.replace('_', ' ')}")
                lines.append(f"- {reason}")
            lines.append("")
        for day, why in sorted(skipped.items()):
            lines.append(f"### {day.isoformat()} · skipped")
            lines.append(f"- {why}")
            lines.append("")
        checkup = self._checkup()
        if checkup:
            lines.append("**Check-up (14 d):**")
            lines.append("")
            lines.append(checkup.rstrip())
            lines.append("")
        drafted = [o for o in outcomes if o.outcome == "drafted"]
        if drafted:
            example = drafted[0].date.isoformat()
            lines.append(
                f'Approve? Reply "approve {example}" or give corrections (e.g. "chicken 300 g").'
            )
        return "\n".join(lines).rstrip() + "\n"
