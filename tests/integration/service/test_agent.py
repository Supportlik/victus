"""Agent run lifecycle, locks and draft creation (SPEC R37–R40, R49–R51)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import (
    Conflict,
    LockHeldByOtherRun,
    NotFound,
    RunNotActive,
    ValidationFailed,
)
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as uc
from victus.application.use_cases import captures as captures_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import drafts as drafts_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage

pytestmark = pytest.mark.service

DAY2 = date(2026, 3, 11)


def _capture(factory: UowFactory, ctx: TenantContext, text: str, day: date | None) -> str:
    view = captures_uc.UploadCapture(factory, ctx, InMemoryBlobStorage()).execute(
        captures_uc.UploadInput(text=text, target_date=day)
    )
    return view.id


def _draft(run_id: str, day: date, capture_id: str, skyr: int, **extra: Any) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "run_id": run_id,
        "date": day.isoformat(),
        "source_captures": [capture_id],
        "meals": [
            {
                "name": "Dinner",
                "time": "19:30",
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
                        "portion_label": "whole tub",
                        "base_quantity": 400,
                        "estimated": False,
                        "quantity_estimated": False,
                        "confidence": 0.9,
                        "rationale": "Skyr is always eaten as the whole tub.",
                        "source_kind": "text",
                        "source_capture_id": capture_id,
                    },
                    {
                        "raw_text": "some restaurant chips",
                        "candidates": [],
                        "chosen_consumable_id": None,
                        "one_off_nutrition_per_100": {
                            "kcal": 312,
                            "protein": 3.4,
                            "carbs": 41,
                            "fat": 15,
                            "fiber": 3.5,
                            "salt": 0.6,
                            "source": "typical value",
                        },
                        "quantity": 150,
                        "unit_code": "g",
                        "estimated": True,
                        "quantity_estimated": True,
                        "confidence": 0.4,
                        "rationale": "No product in the catalogue; portion guessed.",
                        "source_kind": "text",
                        "source_capture_id": capture_id,
                    },
                ],
            }
        ],
        "training": "rest",
        "notes": ["Protein at the optimum."],
        "open_questions": ["Chips: how many grams?"],
        "prompt_version": "test-1",
    }
    draft.update(extra)
    return draft


def test_queue_then_begin_locks_days_from_open_captures(
    factory: UowFactory, alice: TenantContext
) -> None:
    c1 = _capture(factory, alice, "breakfast: skyr", DAY)
    _capture(factory, alice, "dinner: chips", DAY2)
    _capture(factory, alice, "no day yet", None)
    queued = uc.QueueAgentRun(factory, alice).execute("historical")
    assert queued.status == "queued" and queued.runner == "worker" and queued.days == []
    started = uc.BeginAgentRun(factory, alice).execute(run_id=queued.id, model="test-model")
    assert started.run.status == "running" and started.run.model == "test-model"
    assert started.locked_days == [DAY, DAY2] and started.skipped_days == {}
    locks = uc.ListAgentLocks(factory, alice).execute()
    assert {lk.date for lk in locks} == {DAY, DAY2}
    assert all(lk.run_id == queued.id for lk in locks)
    # beginning it twice is refused
    with pytest.raises(RunNotActive):
        uc.BeginAgentRun(factory, alice).execute(run_id=queued.id)
    # explicit ranges only count days with open captures
    ranged = uc.QueueAgentRun(factory, alice).execute(
        "batch", start=date(2026, 3, 1), end=date(2026, 3, 31)
    )
    assert len(ranged.days) == 31
    uc.CancelAgentRun(factory, alice).execute(queued.id)
    began = uc.BeginAgentRun(factory, alice).execute(run_id=ranged.id)
    assert began.locked_days == [DAY, DAY2]
    assert c1 in {c.id for c in captures_uc.ListCaptures(factory, alice).execute(status="new")}


def test_second_run_skips_locked_days_with_reason(
    factory: UowFactory, alice: TenantContext
) -> None:
    _capture(factory, alice, "skyr", DAY)
    first = uc.BeginAgentRun(factory, alice).execute(runner="external", dates=[DAY])
    assert first.locked_days == [DAY]
    second = uc.BeginAgentRun(factory, alice).execute(runner="worker", dates=[DAY])
    assert second.locked_days == [] and DAY in second.skipped_days
    assert first.run.id in second.skipped_days[DAY] and "external" in second.skipped_days[DAY]
    # the same run may re-acquire / extend its own lock
    assert uc.AcquireDayLock(factory, alice).execute(first.run.id, DAY) is True
    assert uc.ExtendDayLock(factory, alice).execute(first.run.id, DAY) is True
    assert uc.ExtendDayLock(factory, alice).execute(second.run.id, DAY) is False
    with pytest.raises(LockHeldByOtherRun):
        uc.ReleaseDayLock(factory, alice).execute(second.run.id, DAY)
    assert uc.ReleaseDayLock(factory, alice).execute(first.run.id, DAY) is True
    assert uc.ListAgentLocks(factory, alice).execute() == []
    with pytest.raises(ValidationFailed):
        uc.BeginAgentRun(factory, alice).execute(runner="robot", dates=[DAY])
    # historical mode with explicit dates only takes days that have open captures
    empty = uc.BeginAgentRun(factory, alice).execute(runner="worker", dates=[DAY2])
    assert empty.locked_days == [] and empty.skipped_days == {}


def test_create_draft_writes_day_items_ad_hoc_and_thread(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = _capture(factory, alice, "a whole tub of skyr and some chips", DAY)
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", dates=[DAY])
    result = uc.CreateDraft(factory, alice).execute(_draft(run.run.id, DAY, cap, skyr))
    assert result.created_items == 2 and result.created_ad_hoc == 1
    assert result.captures_assigned == 1 and result.questions == 1
    day = result.day
    assert day.status == "draft" and day.has_drafts and day.training_type == "rest"
    items = day.meals[0].line_items
    assert all(li.is_draft for li in items)
    skyr_item = next(li for li in items if li.consumable_id == skyr)
    assert skyr_item.base_amount == 400.0 and skyr_item.confidence == 0.9
    assert skyr_item.alternatives and skyr_item.alternatives[0]["consumable_id"] == skyr
    chips = next(li for li in items if li.consumable_id != skyr)
    assert chips.consumable_kind == "ad_hoc" and chips.estimated and chips.amount_estimated
    assert chips.kcal == pytest.approx(468.0)  # 312 kcal/100 g × 150 g
    assert "approve" in result.markdown.lower()
    assert captures_uc.GetCapture(factory, alice).execute(cap).status == "assigned"
    ctx_view = uc.GetDayContext(factory, alice).execute(DAY)
    kinds = [(m.role, m.kind) for m in ctx_view.thread]
    assert ("agent", "note") in kinds and ("agent", "question") in kinds
    assert ctx_view.locked_by_run_id == run.run.id
    assert [c.id for c in ctx_view.captures] == [cap]
    # the run remembers the prompt version from the draft
    assert uc.GetAgentRun(factory, alice).execute(run.run.id).prompt_version == "test-1"


def test_create_draft_requires_the_lock_and_a_running_run(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = _capture(factory, alice, "skyr", DAY)
    holder = uc.BeginAgentRun(factory, alice).execute(runner="external", dates=[DAY])
    intruder = uc.BeginAgentRun(factory, alice).execute(
        runner="worker", mode="manual", dates=[DAY2]
    )
    with pytest.raises(LockHeldByOtherRun):
        uc.CreateDraft(factory, alice).execute(_draft(intruder.run.id, DAY, cap, skyr))
    # a day nobody locked
    with pytest.raises(LockHeldByOtherRun):
        uc.CreateDraft(factory, alice).execute(_draft(holder.run.id, date(2026, 3, 12), cap, skyr))
    finished = uc.FinishAgentRun(factory, alice).execute(holder.run.id, summary_md="done")
    assert finished.status == "finished" and finished.summary_md == "done"
    with pytest.raises(RunNotActive):
        uc.CreateDraft(factory, alice).execute(_draft(holder.run.id, DAY, cap, skyr))
    with pytest.raises(NotFound):
        uc.CreateDraft(factory, alice).execute(_draft("run_missing", DAY, cap, skyr))


def test_create_draft_validates_against_schema(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = _capture(factory, alice, "skyr", DAY)
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", dates=[DAY])
    bad = _draft(run.run.id, DAY, cap, skyr)
    del bad["meals"][0]["line_items"][0]["confidence"]
    with pytest.raises(ValidationFailed) as exc:
        uc.CreateDraft(factory, alice).execute(bad)
    assert any("confidence" in e["message"] for e in exc.value.errors)
    # ad-hoc without nutrition values is rejected after schema validation
    no_nutrition = _draft(run.run.id, DAY, cap, skyr)
    del no_nutrition["meals"][0]["line_items"][1]["one_off_nutrition_per_100"]
    with pytest.raises(ValidationFailed):
        uc.CreateDraft(factory, alice).execute(no_nutrition)
    # nothing was written by the failed attempts
    assert uc.GetDayContext(factory, alice).execute(DAY).day is None


def test_finish_releases_locks_and_records_usage(factory: UowFactory, alice: TenantContext) -> None:
    _capture(factory, alice, "skyr", DAY)
    run = uc.BeginAgentRun(factory, alice).execute(
        runner="worker", mode="manual", dates=[DAY, DAY2]
    )
    assert run.locked_days == [DAY, DAY2]
    t0 = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    uc.RecordAgentSession(factory, alice).execute(
        run.run.id,
        DAY,
        model="m",
        prompt_version="v1",
        input_tokens=1000,
        output_tokens=200,
        cost_usd=0.01,
        outcome="drafted",
        started_at=t0,
        finished_at=t0,
    )
    uc.RecordAgentSession(factory, alice).execute(
        run.run.id,
        DAY2,
        model="m",
        prompt_version="v1",
        input_tokens=500,
        output_tokens=100,
        cost_usd=0.005,
        outcome="no_captures",
        started_at=t0,
        finished_at=t0,
    )
    view = uc.GetAgentRun(factory, alice).execute(run.run.id)
    assert view.input_tokens == 1500 and view.output_tokens == 300
    assert view.cost_usd == pytest.approx(0.015)
    assert [s.date for s in view.sessions] == [DAY, DAY2]
    done = uc.FinishAgentRun(factory, alice).execute(
        run.run.id, status="budget_exceeded", summary_md="## Drafts", error="budget"
    )
    assert done.status == "budget_exceeded" and done.error == "budget"
    assert uc.ListAgentLocks(factory, alice).execute() == []
    # finishing twice is a no-op, cancelling a finished run is a conflict
    again = uc.FinishAgentRun(factory, alice).execute(run.run.id, status="finished")
    assert again.status == "budget_exceeded"
    with pytest.raises(Conflict):
        uc.CancelAgentRun(factory, alice).execute(run.run.id)
    with pytest.raises(ValidationFailed):
        uc.FinishAgentRun(factory, alice).execute(run.run.id, status="running")


def test_cancel_running_run_and_force_unlock(factory: UowFactory, alice: TenantContext) -> None:
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", mode="manual", dates=[DAY])
    cancelled = uc.CancelAgentRun(factory, alice).execute(run.run.id)
    assert cancelled.status == "cancelled" and uc.ListAgentLocks(factory, alice).execute() == []
    other = uc.BeginAgentRun(factory, alice).execute(runner="external", mode="manual", dates=[DAY])
    assert other.locked_days == [DAY]
    assert uc.ForceUnlockDay(factory, alice).execute(DAY) is True
    assert uc.ForceUnlockDay(factory, alice).execute(DAY) is False
    listed = uc.ListAgentRuns(factory, alice).execute(status="running")
    assert [r.id for r in listed] == [other.run.id]


def test_follow_up_runs_merge_when_claimed(factory: UowFactory, alice: TenantContext) -> None:
    from victus.application.use_cases import day_logs as days_uc

    # a locked day: messages queue follow-ups
    holder = uc.BeginAgentRun(factory, alice).execute(runner="worker", mode="manual", dates=[DAY])
    days_uc.AddDayMessage(factory, alice).execute(DAY, "also an apple")
    queued = [r for r in uc.ListAgentRuns(factory, alice).execute() if r.status == "queued"]
    assert len(queued) == 1 and queued[0].mode == "follow_up"
    uc.FinishAgentRun(factory, alice).execute(holder.run.id)
    started = uc.BeginAgentRun(factory, alice).execute(run_id=queued[0].id)
    assert started.locked_days == [DAY] and started.run.mode == "follow_up"
    assert len(started.run.captures) == 1


def test_approval_after_draft_marks_captures_processed(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = _capture(factory, alice, "skyr and chips", DAY)
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", dates=[DAY])
    uc.CreateDraft(factory, alice).execute(_draft(run.run.id, DAY, cap, skyr))
    uc.FinishAgentRun(factory, alice).execute(run.run.id, summary_md="ok")
    approved = drafts_uc.ApproveDay(factory, alice).execute(DAY, [], close=True)
    assert approved.status == "closed" and not approved.has_drafts and approved.reliable is True
    assert captures_uc.GetCapture(factory, alice).execute(cap).status == "processed"


def test_a_second_verdict_replaces_the_first(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-085: one verdict per day, so a re-run corrects it instead of stacking."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", mode="manual", dates=[DAY])
    first = uc.AddAgentMessage(factory, alice).execute(
        run.run.id, DAY, "summary", "A rest day that came in light."
    )
    uc.AddAgentMessage(factory, alice).execute(run.run.id, DAY, "note", "Fibre is the weak one.")
    second = uc.AddAgentMessage(factory, alice).execute(
        run.run.id, DAY, "summary", "Two ready meals and a protein pudding. 20 g of protein short."
    )
    assert first.id != second.id
    thread = day_uc.GetDayThread(factory, alice).execute(DAY)
    assert [m.content for m in thread if m.kind == "summary"] == [second.content]
    # notes are each about a different thing, so they accumulate as they always did
    assert [m.content for m in thread if m.kind == "note"] == ["Fibre is the weak one."]
    # and the day carries the current verdict, which is what it shows above its meals
    assert day_uc.GetDay(factory, alice).execute(DAY).verdict == second.content
    with pytest.raises(ValidationFailed):
        uc.AddAgentMessage(factory, alice).execute(run.run.id, DAY, "summary", "   ")
    with pytest.raises(ValidationFailed):
        uc.AddAgentMessage(factory, alice).execute(run.run.id, DAY, "verdict", "wrong kind")


def test_agent_runs_are_tenant_scoped(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    run = uc.BeginAgentRun(factory, alice).execute(runner="worker", mode="manual", dates=[DAY])
    with pytest.raises(NotFound):
        uc.GetAgentRun(factory, bob).execute(run.run.id)
    assert uc.ListAgentRuns(factory, bob).execute() == []
    assert uc.ListAgentLocks(factory, bob).execute() == []
    # bob can lock the same calendar day for his own tenant
    bob_run = uc.BeginAgentRun(factory, bob).execute(runner="worker", mode="manual", dates=[DAY])
    assert bob_run.locked_days == [DAY]
