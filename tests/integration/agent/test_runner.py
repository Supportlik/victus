"""End-to-end runner and worker tests with a scripted model (no network).

T-AGT-001 queue → worker → draft → approve
T-AGT-002 lock conflict between an external run and the worker
T-AGT-003 follow-up merge
T-AGT-004 budget exhausted
T-AGT-005 model refusal
T-AGT-006 no model configured
T-AGT-007 assess run judges a frozen report
T-AGT-008 assess run with nothing waiting
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.agent.model import ScriptedModelClient, ScriptedTurn
from victus.agent.runner import RunProcessor, load_prompts
from victus.agent.worker import Worker
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.mcp.tools import ToolContext, dispatch

from .conftest import DAY


def _capture(factory: UowFactory, ctx: TenantContext, blobs: InMemoryBlobStorage, text: str) -> str:
    view = capture_uc.UploadCapture(factory, ctx, blobs).execute(
        capture_uc.UploadInput(text=text, target_date=DAY)
    )
    return view.id


def _draft_input(run_id: str, capture_id: str, skyr: int) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "date": DAY.isoformat(),
        "source_captures": [capture_id],
        "meals": [
            {
                "name": "Breakfast",
                "time": "07:40",
                "line_items": [
                    {
                        "raw_text": "a whole tub of skyr",
                        "candidates": [
                            {
                                "consumable_id": skyr,
                                "name": "Skyr natural",
                                "score": 0.93,
                                "tier": 2,
                            }
                        ],
                        "chosen_consumable_id": skyr,
                        "quantity": 1,
                        "unit_code": "tub",
                        "estimated": False,
                        "quantity_estimated": False,
                        "confidence": 0.9,
                        "rationale": "Skyr is always eaten as the whole tub.",
                        "source_kind": "text",
                        "source_capture_id": capture_id,
                    }
                ],
            }
        ],
        "training": "rest",
        "notes": ["Protein at the optimum."],
        "open_questions": ["Chips: how much?"],
    }


def _scripted(run_id_holder: dict[str, str], capture_id: str, skyr: int) -> ScriptedModelClient:
    """product_search → draft_create (run_id taken from the task prompt) → done."""

    def draft(memo: dict[str, Any]) -> dict[str, Any]:
        return _draft_input(run_id_holder["run_id"], capture_id, skyr)

    return ScriptedModelClient(
        turns=[
            ScriptedTurn(tool_calls=[("product_search", {"q": "skyr"})]),
            ScriptedTurn(tool_calls=[("draft_create", draft)]),
            ScriptedTurn(text="Drafted breakfast: one tub of skyr."),
        ]
    )


def _worker(
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    blobs: InMemoryBlobStorage,
    model: ScriptedModelClient | None,
    tmp_path: Any,
) -> Worker:
    return Worker(
        config,
        session_factory,
        model_factory=lambda _cfg: model,
        blobs=blobs,
        heartbeat_path=tmp_path / "alive",
    )


@pytest.fixture
def run_id_holder() -> dict[str, str]:
    return {}


def _queue(factory: UowFactory, ctx: TenantContext, holder: dict[str, str]) -> str:
    run = agent_uc.QueueAgentRun(factory, ctx).execute("historical")
    holder["run_id"] = run.id
    return run.id


def test_queue_worker_draft_approve(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    make_tool_ctx: Callable[[TenantContext], ToolContext],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    capture_id = _capture(factory, alice, blobs, "breakfast: a whole tub of skyr")
    run_id = _queue(factory, alice, run_id_holder)
    model = _scripted(run_id_holder, capture_id, skyr)
    worker = _worker(config, session_factory, blobs, model, tmp_path)

    outcomes = worker.run_once()

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.run.status == "finished"
    assert outcome.run.id == run_id
    assert [o.outcome for o in outcome.days] == ["drafted"]
    assert (tmp_path / "alive").exists()
    # the model saw only worker tools, the prompt and the day context
    first_call = model.calls[0]
    assert "day_approve" not in {t["name"] for t in first_call["tools"]}
    assert run_id in first_call["messages"][0]["content"][0]["text"]
    assert load_prompts().version == outcome.run.prompt_version

    day = day_uc.GetDay(factory, alice).execute(DAY)
    assert day.status == "draft"
    items = [li for m in day.meals for li in m.line_items]
    assert len(items) == 1 and items[0].is_draft and items[0].base_amount == 400
    run = agent_uc.GetAgentRun(factory, alice).execute(run_id)
    assert len(run.sessions) == 1 and run.sessions[0].outcome == "drafted"
    assert run.input_tokens == 3_000 and run.output_tokens == 600
    assert run.summary_md is not None
    assert f"### {DAY.isoformat()}" in run.summary_md
    assert "- ? Chips: how much?" in run.summary_md
    assert "Approve?" in run.summary_md
    cap = capture_uc.GetCapture(factory, alice).execute(capture_id)
    assert cap.status == "assigned"
    thread = day_uc.GetDayThread(factory, alice).execute(DAY)
    kinds = {m.kind for m in thread if m.role == "agent"}
    assert {"note", "question"} <= kinds
    # the draft's item table is the run's page, not the day's: `summary` is the day's
    # verdict now, and this scripted model never wrote one
    assert "summary" not in kinds and day_uc.GetDay(factory, alice).execute(DAY).verdict is None
    assert agent_uc.ListAgentLocks(factory, alice).execute() == []

    # approval through the same tool registry an external chat would use
    tc = make_tool_ctx(alice)
    result = dispatch(tc, "day_approve", {"date": DAY.isoformat(), "close": True})
    assert isinstance(result, dict) and result["status"] == "closed"
    assert capture_uc.GetCapture(factory, alice).execute(capture_id).status == "processed"


def test_external_run_locks_day_and_worker_skips_it(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    make_tool_ctx: Callable[[TenantContext], ToolContext],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    capture_id = _capture(factory, alice, blobs, "lunch: skyr")
    tc = make_tool_ctx(alice)
    started = dispatch(tc, "agent_run_start", {"mode": "historical"})
    assert isinstance(started, dict) and started["locked_days"] == [DAY.isoformat()]

    run_id = _queue(factory, alice, run_id_holder)
    model = _scripted(run_id_holder, capture_id, skyr)
    outcomes = _worker(config, session_factory, blobs, model, tmp_path).run_once()
    assert outcomes[0].run.status == "finished"
    assert outcomes[0].days == []
    assert DAY in outcomes[0].skipped and "locked by external" in outcomes[0].skipped[DAY]
    assert model.calls == []  # no session was opened
    assert f"### {DAY.isoformat()} · skipped" in outcomes[0].summary_md

    # a second external start for the same day is skipped as well
    again = dispatch(tc, "agent_run_start", {"mode": "historical"})
    assert isinstance(again, dict) and again["locked_days"] == []
    assert DAY.isoformat() in again["skipped_days"]
    dispatch(tc, "agent_run_finish", {"run_id": started["run_id"], "summary": "done"})
    assert agent_uc.ListAgentLocks(factory, alice).execute() == []
    assert run_id


def test_follow_up_runs_merge(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    capture_id = _capture(factory, alice, blobs, "breakfast: skyr")
    _queue(factory, alice, run_id_holder)
    model = _scripted(run_id_holder, capture_id, skyr)
    _worker(config, session_factory, blobs, model, tmp_path).run_once()

    # two messages on the drafted day → exactly one queued follow-up carrying both captures
    day_uc.AddDayMessage(factory, alice).execute(DAY, "the skyr was only half a tub")
    day_uc.AddDayMessage(factory, alice).execute(DAY, "and a banana")
    queued = agent_uc.ListAgentRuns(factory, alice).execute(status="queued")
    assert len(queued) == 1 and queued[0].mode == "follow_up" and len(queued[0].captures) == 2

    run_id_holder["run_id"] = queued[0].id
    follow = ScriptedModelClient(turns=[ScriptedTurn(text="Nothing to change.")])
    outcomes = _worker(config, session_factory, blobs, follow, tmp_path).run_once()
    assert outcomes[0].run.mode == "follow_up"
    assert outcomes[0].days[0].outcome == "no_draft"
    ctx_text = follow.calls[0]["messages"][0]["content"][1]["text"]
    assert "half a tub" in ctx_text and "banana" in ctx_text


def test_budget_exhausted_stops_the_run(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    capture_id = _capture(factory, alice, blobs, "dinner: skyr")
    config.agent.budget.max_output_tokens = 100  # first turn already crosses it
    _queue(factory, alice, run_id_holder)
    model = _scripted(run_id_holder, capture_id, skyr)
    outcomes = _worker(config, session_factory, blobs, model, tmp_path).run_once()
    assert outcomes[0].run.status == "budget_exceeded"
    assert outcomes[0].days[0].outcome == "budget_exceeded"
    assert "budget exhausted" in (outcomes[0].run.error or "")
    assert len(model.calls) == 1
    assert agent_uc.ListAgentLocks(factory, alice).execute() == []


def test_refusal_is_recorded(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    _capture(factory, alice, blobs, "snack: skyr")
    _queue(factory, alice, run_id_holder)
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                stop_reason="refusal",
                stop_details={"type": "refusal", "category": "other", "explanation": "declined"},
            )
        ]
    )
    outcomes = _worker(config, session_factory, blobs, model, tmp_path).run_once()
    assert outcomes[0].days[0].outcome == "refused"
    run = agent_uc.GetAgentRun(factory, alice).execute(outcomes[0].run.id)
    assert run.sessions[0].outcome == "refused"
    assert "declined" in (run.error or "")
    assert run.status == "finished"  # a refusal is a recorded outcome, not a crash


def test_no_model_configured_fails_the_run(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    run_id_holder: dict[str, str],
    tmp_path: Any,
) -> None:
    _capture(factory, alice, blobs, "skyr")
    _queue(factory, alice, run_id_holder)
    outcomes = _worker(config, session_factory, blobs, None, tmp_path).run_once()
    assert outcomes[0].run.status == "failed"
    assert "anthropic_api_key" in (outcomes[0].run.error or "")
    assert agent_uc.ListAgentLocks(factory, alice).execute() == []


def test_cron_queues_one_historical_run_per_tenant(
    factory: UowFactory,
    alice: TenantContext,
    bob: TenantContext,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    blobs: InMemoryBlobStorage,
    tmp_path: Any,
) -> None:
    config.agent.enabled = True
    config.agent.cron = "0 * * * *"
    worker = _worker(config, session_factory, blobs, None, tmp_path)
    at = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)
    assert worker.queue_scheduled_runs(at) == 2
    assert worker.queue_scheduled_runs(at) == 0  # same minute: no duplicate
    assert worker.queue_scheduled_runs(at.replace(minute=30)) == 0  # cron does not match
    assert len(agent_uc.ListAgentRuns(factory, alice).execute(status="queued")) == 1
    assert len(agent_uc.ListAgentRuns(factory, bob).execute(status="queued")) == 1


def test_processor_transcribes_audio_before_the_session(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    make_tool_ctx: Callable[[TenantContext], ToolContext],
    run_id_holder: dict[str, str],
) -> None:
    view = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            data=b"RIFF....WAVEfake", filename="note.wav", mime="audio/wav", target_date=DAY
        )
    )
    _queue(factory, alice, run_id_holder)
    model = _scripted(run_id_holder, view.id, skyr)
    tc = make_tool_ctx(alice)
    outcome = RunProcessor(tc, model, config).process(run_id_holder["run_id"])
    assert outcome.run.status == "finished"
    ctx_json = json.loads(model.calls[0]["messages"][0]["content"][1]["text"].split("\n", 1)[1])
    assert ctx_json["captures"][0]["transcript"] == "two slices of rye bread with butter"


def test_assess_run_judges_a_frozen_report(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-007: an `assess` run writes the judgement of a frozen report (R72).

    It locks no day, so it cannot collide with drafting, and it must not need the day
    machinery: a snapshot's numbers are already fixed.
    """
    from victus.application.use_cases import snapshots as snap_uc

    snap = snap_uc.FreezeReport(factory, alice).execute(
        "checkup",
        "Check-up",
        {"blocks": [{"meta": {"type": "kpi_tile", "title": "Weight"}, "value": 86.4}]},
        period_start=date(2026, 3, 1),
        period_end=DAY,
        today=DAY,
        label="before the trip",
    )
    assert snap.status == "frozen"

    run = agent_uc.QueueAgentRun(factory, alice).execute("assess")
    assessment = "Weight is 86.4 kg, 1.4 kg from the goal. Hold the current intake."
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                tool_calls=[
                    ("report_assess", {"snapshot_id": snap.id, "assessment_md": assessment})
                ]
            ),
            ScriptedTurn(text="Assessed."),
        ]
    )
    worker = _worker(config, session_factory, blobs, model, tmp_path)

    outcomes = worker.run_once()

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.run.status == "finished"
    assert outcome.run.id == run.id
    assert [o.outcome for o in outcome.days] == ["assessed"]
    assert outcome.summary_md is not None
    assert "before the trip" in outcome.summary_md

    stored = snap_uc.GetSnapshot(factory, alice).execute(snap.id)
    assert stored.status == "assessed"
    assert stored.assessment_md == assessment
    # the assessment records which prompt wrote it, not "external"
    assert stored.prompt_version == load_prompts().version
    # no day was locked, so drafting is unaffected
    with factory(alice) as uow:
        assert list(uow.agent.locks()) == []


def test_assess_run_says_so_when_nothing_is_waiting(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-008: an assess run with no frozen report finishes without calling the model."""
    agent_uc.QueueAgentRun(factory, alice).execute("assess")
    model = ScriptedModelClient(turns=[ScriptedTurn(text="should not be called")])
    worker = _worker(config, session_factory, blobs, model, tmp_path)

    outcomes = worker.run_once()

    assert outcomes[0].run.status == "finished"
    assert outcomes[0].days == []
    assert model.calls == []
    assert "No frozen report" in (outcomes[0].summary_md or "")
