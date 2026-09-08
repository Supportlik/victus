"""T-SVC-057…060: freezing a report, assessing it once, and the active goal."""

from __future__ import annotations

from datetime import date

import pytest

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import snapshots as uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.reports.sqlalchemy_source import active_goal, settings_from_data

PERIOD = (date(2026, 1, 1), date(2026, 1, 14))
RESULT = {"title": "Am I on track?", "blocks": [{"meta": {"type": "kpi_tile"}, "value": 86.4}]}


def _freeze(factory: UowFactory, ctx: TenantContext, label: str | None = None):  # type: ignore[no-untyped-def]
    return uc.FreezeReport(factory, ctx).execute(
        "checkup",
        "Am I on track?",
        RESULT,
        period_start=PERIOD[0],
        period_end=PERIOD[1],
        today=date(2026, 1, 14),
        label=label,
    )


def test_freeze_keeps_the_numbers_and_lists_newest_first(
    factory: UowFactory, alice: TenantContext
) -> None:
    first = _freeze(factory, alice, "before the trip")
    second = _freeze(factory, alice)
    assert first.status == "frozen" and first.label == "before the trip"
    listed = uc.ListSnapshots(factory, alice).execute()
    assert [s.id for s in listed] == [second.id, first.id]
    assert listed[0].result is None  # the list stays small
    detail = uc.GetSnapshot(factory, alice).execute(first.id)
    assert detail.result == RESULT

    with pytest.raises(ValidationFailed):
        uc.FreezeReport(factory, alice).execute(
            "checkup",
            "t",
            {},
            period_start=PERIOD[0],
            period_end=PERIOD[1],
            today=PERIOD[1],
        )


def test_a_snapshot_carries_exactly_one_assessment(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    snap = _freeze(factory, alice)
    assert [s.id for s in uc.PendingSnapshots(factory, alice).execute()] == [snap.id]
    assessed = uc.AssessSnapshot(factory, alice).execute(
        snap.id, "  On track: 0.9 kg per week.  ", model="claude-opus-5", cost_usd=0.02
    )
    assert assessed.status == "assessed" and assessed.assessment_md == "On track: 0.9 kg per week."
    assert assessed.cost_usd == 0.02
    assert uc.PendingSnapshots(factory, alice).execute() == []

    with pytest.raises(Conflict):
        uc.AssessSnapshot(factory, alice).execute(snap.id, "second opinion")
    with pytest.raises(ValidationFailed):
        uc.AssessSnapshot(factory, alice).execute(_freeze(factory, alice).id, "   ")
    with pytest.raises(NotFound):
        uc.GetSnapshot(factory, bob).execute(snap.id)


def test_snapshots_can_be_deleted(factory: UowFactory, alice: TenantContext) -> None:
    snap = _freeze(factory, alice)
    uc.DeleteSnapshot(factory, alice).execute(snap.id)
    with pytest.raises(NotFound):
        uc.GetSnapshot(factory, alice).execute(snap.id)


def test_the_active_goal_drives_the_report_settings() -> None:
    legacy = {"goal": {"weight_kg": 80, "date": "2027-01-31"}}
    assert settings_from_data(legacy).goal_kg == 80

    several = {
        "goals": [
            {"name": "plan", "weight_kg": 80, "date": "2027-01-31"},
            {"name": "stretch", "weight_kg": 76, "date": "2027-06-30", "active": True},
        ],
        "goal": {"weight_kg": 80, "date": "2027-01-31"},
    }
    settings = settings_from_data(several)
    assert settings.goal_kg == 76 and settings.goal_name == "stretch"
    # without an explicit active flag the first goal wins
    assert (
        active_goal({"goals": [{"name": "a", "weight_kg": 90, "date": "2027-01-01"}]})["name"]
        == "a"
    )
    assert active_goal({}) == {}
