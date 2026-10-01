"""Agent-run use cases: the branches the end-to-end tests do not reach (T-SVC-440..446)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as days_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage

pytestmark = pytest.mark.service


def _capture(factory: UowFactory, ctx: TenantContext, text: str, day: date | None = DAY) -> str:
    return (
        capture_uc.UploadCapture(factory, ctx, InMemoryBlobStorage())
        .execute(capture_uc.UploadInput(text=text, target_date=day))
        .id
    )


def _item(cap_id: str, consumable_id: int | None, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "raw_text": "a tub of skyr",
        "candidates": [],
        "chosen_consumable_id": consumable_id,
        "quantity": 400,
        "unit_code": "g",
        "estimated": False,
        "quantity_estimated": False,
        "confidence": 0.9,
        "rationale": "whole tub",
        "source_kind": "text",
        "source_capture_id": cap_id,
    }
    item.update(over)
    return item


def _running(factory: UowFactory, ctx: TenantContext, day: date = DAY) -> str:
    return uc.BeginAgentRun(factory, ctx).execute(runner="external", dates=[day]).run.id


def test_t_svc_440_queue_rejects_unknown_mode_and_oversized_range(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-440: an unknown agent mode and a range over 366 days are refused."""
    with pytest.raises(ValidationFailed, match="unknown agent mode 'dream'"):
        uc.QueueAgentRun(factory, alice).execute("dream")
    with pytest.raises(ValidationFailed, match="too large"):
        uc.QueueAgentRun(factory, alice).execute(
            start=date(2025, 1, 1), end=date(2025, 1, 1) + timedelta(days=367)
        )
    assert uc.ListAgentRuns(factory, alice).execute() == []


def test_t_svc_441_run_days_ignore_captures_without_a_day(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-441: a queued run's capture without a target day adds no day; the worker
    claiming it locks only the days that come from captures with one."""
    loose = _capture(factory, alice, "some undated note", day=None)
    dated = _capture(factory, alice, "a dated note")
    queued = uc.QueueAgentRun(factory, alice).execute("manual", captures=[loose, dated])
    started = uc.BeginAgentRun(factory, alice).execute(run_id=queued.id)
    assert started.locked_days == [DAY]
    assert started.run.status == "running" and started.run.days == [DAY]


def test_t_svc_442_follow_up_run_absorbs_a_queued_duplicate(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-442: starting a follow-up for a day cancels the queued follow-up for that day
    and takes over its captures; other queued runs are left alone."""
    cap = _capture(factory, alice, "a tub of skyr")
    run_id = _running(factory, alice)
    uc.CreateDraft(factory, alice).execute(
        {
            "run_id": run_id,
            "date": DAY.isoformat(),
            "source_captures": [cap],
            "meals": [{"name": "Breakfast", "line_items": [_item(cap, skyr)]}],
        }
    )
    uc.FinishAgentRun(factory, alice).execute(run_id)
    uc.QueueAgentRun(factory, alice).execute("historical")  # an unrelated queued run
    days_uc.AddDayMessage(factory, alice).execute(DAY, "and a coffee")
    queued = uc.ListAgentRuns(factory, alice).execute(status="queued")
    follow = next(r for r in queued if r.mode == "follow_up")
    other = next(r for r in queued if r.mode != "follow_up")

    started = uc.BeginAgentRun(factory, alice).execute(
        runner="external", mode="follow_up", dates=[DAY]
    )
    assert started.locked_days == [DAY]
    assert follow.captures and set(follow.captures) <= set(started.run.captures)
    merged = uc.GetAgentRun(factory, alice).execute(follow.id)
    assert merged.status == "cancelled" and merged.error == f"merged into run {started.run.id}"
    assert uc.GetAgentRun(factory, alice).execute(other.id).status == "queued"


def test_t_svc_443_acquire_adds_a_day_and_finish_overrides_totals(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-443: acquiring a new day appends it to the run; finishing with totals stores
    the given token counts and cost instead of the rolled-up ones."""
    _capture(factory, alice, "a note")
    run_id = _running(factory, alice)
    later = DAY + timedelta(days=3)
    assert uc.AcquireDayLock(factory, alice).execute(run_id, later) is True
    assert uc.GetAgentRun(factory, alice).execute(run_id).days == [DAY, later]
    done = uc.FinishAgentRun(factory, alice).execute(
        run_id, input_tokens=1200, output_tokens=300, cost_usd=0.02
    )
    assert (done.input_tokens, done.output_tokens, done.cost_usd) == (1200, 300, 0.02)
    assert uc.ListAgentLocks(factory, alice).execute() == []


def test_t_svc_444_draft_on_a_closed_day_is_refused(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-444: a closed day must be reopened before an agent drafts into it."""
    cap = _capture(factory, alice, "a tub of skyr")
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    days_uc.CloseDay(factory, alice).execute(DAY)
    run_id = _running(factory, alice)
    with pytest.raises(Conflict, match="closed"):
        uc.CreateDraft(factory, alice).execute(
            {
                "run_id": run_id,
                "date": DAY.isoformat(),
                "source_captures": [cap],
                "meals": [{"name": "Breakfast", "line_items": [_item(cap, skyr)]}],
            }
        )
    assert days_uc.GetDay(factory, alice).execute(DAY).meals == []


def test_t_svc_445_draft_reuses_meals_and_settles_every_kind_of_capture(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-445: a draft adds to an existing meal of the same name; unknown capture ids
    are skipped, an already processed capture is not re-assigned, and a capture without
    a day is given the drafted day."""
    cap = _capture(factory, alice, "a tub of skyr")
    loose = _capture(factory, alice, "undated skyr", day=None)
    done = _capture(factory, alice, "old skyr note", day=DAY - timedelta(days=1))
    capture_uc.UpdateCapture(factory, alice).execute(done, {"status": "processed"})
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    breakfast = days_uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    run_id = _running(factory, alice)
    result = uc.CreateDraft(factory, alice).execute(
        {
            "run_id": run_id,
            "date": DAY.isoformat(),
            "source_captures": [cap, loose, done, "no-such-capture"],
            "meals": [{"name": " breakfast ", "line_items": [_item(cap, skyr)]}],
        }
    )
    assert [m.id for m in result.day.meals] == [breakfast.id]
    assert result.created_items == 1 and result.captures_assigned == 2
    by_id = {c.id: c for c in capture_uc.ListCaptures(factory, alice).execute()}
    assert by_id[loose].status == "assigned" and by_id[loose].target_date == DAY
    assert by_id[done].status == "processed" and by_id[done].agent_run_id == run_id


def test_t_svc_446_draft_items_without_a_resolvable_quantity(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-446: an unknown chosen consumable is NotFound; a count unit that cannot be
    resolved falls back to the agent's base quantity, and without one it is refused."""
    cap = _capture(factory, alice, "two slices of something")
    run_id = _running(factory, alice)

    def draft(*items: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "date": DAY.isoformat(),
            "source_captures": [cap],
            "meals": [{"name": "Lunch", "time": "12:30", "line_items": list(items)}],
        }

    with pytest.raises(NotFound, match="consumable 999999"):
        uc.CreateDraft(factory, alice).execute(draft(_item(cap, 999999)))
    one_off = {"kcal": 250, "protein": 9, "carbs": 45, "fat": 3, "fiber": 4, "salt": 1.1}
    with pytest.raises(ValidationFailed, match="count units"):
        uc.CreateDraft(factory, alice).execute(
            draft(
                _item(
                    cap,
                    None,
                    raw_text="slice of bread",
                    quantity=2,
                    unit_code="slice",
                    one_off_nutrition_per_100=one_off,
                )
            )
        )
    result = uc.CreateDraft(factory, alice).execute(
        draft(
            _item(
                cap,
                None,
                raw_text="slice of bread",
                quantity=2,
                unit_code="slice",
                base_quantity=80,
                one_off_nutrition_per_100=one_off,
            ),
            _item(cap, skyr, quantity=3, unit_code="piece", base_quantity=150),
        )
    )
    items = result.day.meals[0].line_items
    assert [(li.base_amount, li.unit_code, li.portion_id) for li in items] == [
        (80.0, "slice", None),
        (150.0, "piece", None),
    ]
    assert result.created_ad_hoc == 1 and items[0].estimated is True
    assert items[0].kcal == pytest.approx(200.0)
