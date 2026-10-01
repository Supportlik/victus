"""T-SVC-300…312: a suggestion can be corrected, not only taken or left (R81, R84)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeError,
    TenantContext,
)
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import drafts as draft_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service

DAY = date(2026, 3, 14)
OTHER_DAY = date(2026, 3, 15)
AGENT_SCOPES = frozenset(
    {SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE}
)


@pytest.fixture
def agent(alice: TenantContext) -> TenantContext:
    """An agent token: everything but ``approve``."""
    return TenantContext(tenant_id=alice.tenant_id, token_id="tok_agent", scopes=AGENT_SCOPES)


@pytest.fixture
def other_agent(alice: TenantContext) -> TenantContext:
    """A second token of the same tenant, holding the same scopes."""
    return TenantContext(tenant_id=alice.tenant_id, token_id="tok_other", scopes=AGENT_SCOPES)


def _meals(factory: UowFactory, ctx: TenantContext) -> tuple[int, int]:
    day_uc.CreateDay(factory, ctx).execute(DAY, reliable=True, training_type="rest")
    breakfast = day_uc.AddMeal(factory, ctx).execute(DAY, "Breakfast").id
    lunch = day_uc.AddMeal(factory, ctx).execute(DAY, "Lunch").id
    return breakfast, lunch


def _draft(factory: UowFactory, agent: TenantContext, meal: int, consumable: int) -> int:
    return (
        day_uc.AddLineItem(factory, agent)
        .execute(
            meal,
            day_uc.LineItemInput(consumable_id=consumable, amount=1, unit_code="tub"),
            origin="agent",
            is_draft=True,
        )
        .id
    )


def _thread(factory: UowFactory, ctx: TenantContext) -> list[str]:
    return [
        m.content
        for m in day_uc.GetDayThread(factory, ctx).execute(DAY)
        if m.kind == "correction" and m.role == "system"
    ]


def _audit(factory: UowFactory, ctx: TenantContext, action: str) -> list[dict[str, Any]]:
    with factory(ctx) as uow:
        rows = uow.audit.since(0, limit=1000)
        return [dict(r.diff or {}) for r in rows if r.action == action]


# ── line items ─────────────────────────────────────────────────────────────


def test_t_svc_300_a_line_item_moves_to_another_meal_of_its_day(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-300: `meal_id` moves an item to another meal of the same day, at the end."""
    breakfast, lunch = _meals(factory, alice)
    day_uc.AddLineItem(factory, alice).execute(
        lunch, day_uc.LineItemInput(consumable_id=skyr, amount=50, unit_code="g")
    )
    item = day_uc.AddLineItem(factory, alice).execute(
        breakfast, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    moved = day_uc.UpdateLineItem(factory, alice).execute(item.id, {"meal_id": lunch})
    assert moved.meal_id == lunch
    day = day_uc.GetDay(factory, alice).execute(DAY)
    by_name = {m.name: m for m in day.meals}
    assert by_name["Breakfast"].line_items == []
    assert [li.id for li in by_name["Lunch"].line_items][-1] == item.id
    assert by_name["Lunch"].line_items[-1].amount == 100  # the quantity travels unchanged
    assert {"meal_id": [breakfast, lunch]} in _audit(factory, alice, "line_item.update")


def test_t_svc_301_a_meal_of_another_day_is_refused(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-301: a meal of another day is a validation error; a meal that is not there a 404."""
    breakfast, _ = _meals(factory, alice)
    day_uc.CreateDay(factory, alice).execute(OTHER_DAY, reliable=True, training_type="rest")
    elsewhere = day_uc.AddMeal(factory, alice).execute(OTHER_DAY, "Dinner").id
    item = day_uc.AddLineItem(factory, alice).execute(
        breakfast, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    with pytest.raises(ValidationFailed) as refused:
        day_uc.UpdateLineItem(factory, alice).execute(item.id, {"meal_id": elsewhere})
    assert refused.value.errors == [{"field": "meal_id", "message": "another day"}]
    with pytest.raises(NotFound):
        day_uc.UpdateLineItem(factory, alice).execute(item.id, {"meal_id": 99_999})
    assert day_uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0].id == item.id


def test_t_svc_302_moving_a_fact_is_a_decision_moving_a_draft_is_not(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-302: the agent may move its own draft between meals, never an approved item."""
    breakfast, lunch = _meals(factory, alice)
    fact = day_uc.AddLineItem(factory, alice).execute(
        breakfast, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    draft = _draft(factory, agent, breakfast, skyr)
    with pytest.raises(ScopeError):
        day_uc.UpdateLineItem(factory, agent).execute(fact.id, {"meal_id": lunch})
    assert day_uc.UpdateLineItem(factory, agent).execute(draft, {"meal_id": lunch}).meal_id == lunch
    # an actor's own move is not a person's correction, so the thread says nothing
    assert _thread(factory, alice) == []


def test_t_svc_303_a_persons_correction_is_told_in_the_day_thread(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-303: correcting the agent's draft — saved, accepted or approved — is in the thread."""
    breakfast, lunch = _meals(factory, alice)
    saved = _draft(factory, agent, breakfast, skyr)
    accepted = _draft(factory, agent, breakfast, skyr)
    approved = _draft(factory, agent, breakfast, skyr)
    mine = day_uc.AddLineItem(factory, alice).execute(
        breakfast, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )

    day_uc.UpdateLineItem(factory, alice).execute(
        saved, {"amount": 300, "unit_code": "g", "meal_id": lunch, "amount_estimated": True}
    )
    day_uc.UpdateLineItem(factory, alice).execute(saved, {"amount": 300, "unit_code": "g"})
    day_uc.UpdateLineItem(factory, alice).execute(mine.id, {"amount": 120, "unit_code": "g"})
    draft_uc.ApproveLineItem(factory, alice).execute(
        accepted, draft_uc.DraftCorrection(line_item_id=accepted, amount=2)
    )
    draft_uc.ApproveDay(factory, alice).execute(
        DAY,
        [draft_uc.DraftCorrection(line_item_id=approved, amount=250, unit_code="g")],
        close=False,
    )

    notes = _thread(factory, alice)
    assert notes == [
        "Corrected Skyr natural: amount 1 tub → 300 g; meal Breakfast → Lunch; "
        "amount estimated no → yes",
        "Corrected Skyr natural: amount 1 tub → 2 tub",
        "Corrected Skyr natural: amount 1 tub → 250 g",
    ]  # nothing for the unchanged second save, nothing for the person's own item


# ── amending a proposal ────────────────────────────────────────────────────


def test_t_svc_304_a_person_amends_a_correction_and_the_agents_reading_stays(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-304: the amendment merges, `null` withdraws, the original is kept once, and audited."""
    filed = prop_uc.ProposeProductChange(factory, agent).execute(
        skyr, {"kcal": 70, "protein": 12, "brand": "Dairy"}
    )
    first = prop_uc.AmendProposal(factory, alice).execute(filed.id, {"kcal": 66, "brand": None})
    assert first.status == "pending"
    assert first.changes == {"kcal": 66, "protein": 12}
    assert first.proposed == {"kcal": 70, "protein": 12, "brand": "Dairy"}
    second = prop_uc.AmendProposal(factory, alice).execute(filed.id, {"fat": 0.5})
    assert second.changes == {"kcal": 66, "protein": 12, "fat": 0.5}
    assert second.proposed == {"kcal": 70, "protein": 12, "brand": "Dairy"}, "kept from the first"
    assert products_uc.GetProduct(factory, alice).execute(skyr).kcal == 63  # nothing applied
    amended = _audit(factory, alice, "product.proposal.amend")
    assert amended[0]["before"] == {"brand": "Dairy", "kcal": 70}
    assert amended[0]["after"] == {"brand": None, "kcal": 66}
    assert amended[0]["by"] == "person"


def test_t_svc_305_a_new_products_one_off_follows_the_amendment(
    factory: UowFactory, alice: TenantContext, agent: TenantContext
) -> None:
    """T-SVC-305: amending a `new` proposal corrects the day it was logged on, name required."""
    filed = prop_uc.ProposeNewProduct(factory, agent).execute(
        products_uc.ProductInput(name="Oat bar", kcal=400, protein=8, carbs=60, fat=12),
        portions=[{"unit_code": "piece", "label": "bar", "amount": 50}],
    )
    assert filed.consumable_id is not None
    meal = _meals(factory, alice)[0]
    day_uc.AddLineItem(factory, alice).execute(
        meal, day_uc.LineItemInput(consumable_id=filed.consumable_id, amount=50, unit_code="g")
    )
    assert day_uc.GetDay(factory, alice).execute(DAY).macros.kcal == pytest.approx(200)

    fixed = prop_uc.AmendProposal(factory, alice).execute(
        filed.id,
        {
            "name": " Oat bar crunchy ",
            "kcal": 440,
            "portions": [{"unit_code": "piece", "label": "bar", "amount": 45}],
        },
    )
    assert fixed.changes["name"] == "Oat bar crunchy"
    assert fixed.changes["portions"] == [
        {"unit_code": "piece", "label": "bar", "amount": 45, "op": "add"}
    ]
    day = day_uc.GetDay(factory, alice).execute(DAY)
    assert day.macros.kcal == pytest.approx(220)
    assert day.meals[0].line_items[0].consumable_name == "Oat bar crunchy"

    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"name": None})
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(
            filed.id, {"portions": [{"op": "delete", "portion_id": 1}]}
        )

    approved = prop_uc.DecideProposal(factory, alice).execute(filed.id, approve=True)
    product = products_uc.GetProduct(factory, alice).execute(filed.consumable_id)
    assert (product.name, product.kcal) == ("Oat bar crunchy", 440)
    assert approved.proposed is not None and approved.proposed["kcal"] == 400


def test_t_svc_306_a_version_keeps_its_day_and_the_rules_of_one(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-306: `valid_from` may move, never go missing or before the version it replaces."""
    products_uc.NewProductVersion(factory, alice).execute(skyr, date(2026, 2, 1), {"kcal": 64})
    current = products_uc.ProductVersions(factory, alice).execute(skyr)[-1].id
    filed = prop_uc.ProposeProductVersion(factory, agent).execute(
        current, date(2026, 3, 1), {"kcal": 68}
    )
    moved = prop_uc.AmendProposal(factory, alice).execute(filed.id, {"valid_from": "2026-03-05"})
    assert moved.changes == {"kcal": 68, "valid_from": "2026-03-05"}
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"valid_from": None})
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"valid_from": "2026-01-15"})
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"valid_from": "soon"})
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"kcal": None})
    with pytest.raises(ValidationFailed):
        prop_uc.AmendProposal(factory, alice).execute(filed.id, {"portions": []})


def test_t_svc_307_only_a_pending_proposal_is_amended_and_only_with_sound_values(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-307: decided → conflict, missing → 404, unknown field or bad value → validation."""
    pending = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"kcal": 70})
    for changes in (
        {},
        {"category_id": 3},
        {"kcal": -1},
        {"kcal": "a lot"},
        {"protein": True},
        {"reference_amount": 0},
        {"reference_unit": "oz"},
        {"density_g_per_ml": 0},
        {"name": "  "},
        {"valid_from": "2026-03-01"},
        {"portions": "tub"},
    ):
        with pytest.raises(ValidationFailed):
            prop_uc.AmendProposal(factory, alice).execute(pending.id, changes)
    with pytest.raises(NotFound):
        prop_uc.AmendProposal(factory, alice).execute("nope", {"kcal": 66})

    approved = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"fat": 1})
    prop_uc.DecideProposal(factory, alice).execute(approved.id, approve=True)
    rejected = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"fat": 2})
    prop_uc.DecideProposal(factory, alice).execute(rejected.id, approve=False)
    for decided in (approved.id, rejected.id):
        with pytest.raises(Conflict):
            prop_uc.AmendProposal(factory, alice).execute(decided, {"kcal": 66})
    assert prop_uc.GetProposal(factory, alice).execute(pending.id).changes == {"kcal": 70}


def test_t_svc_308_who_may_amend(
    factory: UowFactory,
    alice: TenantContext,
    agent: TenantContext,
    other_agent: TenantContext,
    skyr: int,
) -> None:
    """T-SVC-308: approve amends anything pending; agent:write only its own, untouched ones."""
    own = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"kcal": 70})
    theirs = prop_uc.ProposeProductChange(factory, other_agent).execute(skyr, {"fat": 1})

    by_agent = prop_uc.AmendProposal(factory, agent).execute(
        own.id, {"kcal": 71}, rationale="read the label again"
    )
    assert by_agent.changes == {"kcal": 71} and by_agent.proposed is None
    assert by_agent.rationale == "read the label again"
    assert _audit(factory, alice, "product.proposal.amend")[0]["by"] == "actor"
    with pytest.raises(ScopeError):
        prop_uc.AmendProposal(factory, agent).execute(theirs.id, {"fat": 2})

    reader = TenantContext(tenant_id=alice.tenant_id, token_id="tok_r", scopes={SCOPE_READ})
    writer = TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_agent", scopes={SCOPE_READ, SCOPE_WRITE}
    )
    approver = TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_a", scopes={SCOPE_READ, SCOPE_APPROVE}
    )
    for ctx in (reader, writer, approver):
        with pytest.raises(ScopeError):
            prop_uc.AmendProposal(factory, ctx).execute(own.id, {"kcal": 72})

    # once a person corrected it, it is no longer only the agent's
    prop_uc.AmendProposal(factory, alice).execute(own.id, {"kcal": 66})
    with pytest.raises(Conflict):
        prop_uc.AmendProposal(factory, agent).execute(own.id, {"kcal": 72})
    # a person may still amend what another token filed
    assert prop_uc.AmendProposal(factory, alice).execute(theirs.id, {"fat": 2}).changes == {
        "fat": 2
    }


def test_t_svc_309_an_approval_with_corrections_keeps_what_was_proposed(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-309: `changes` on approve keep the original; an approval as filed keeps none."""
    corrected = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"kcal": 70})
    decided = prop_uc.DecideProposal(factory, alice).execute(
        corrected.id, approve=True, changes={"kcal": 65}
    )
    assert decided.changes == {"kcal": 65} and decided.proposed == {"kcal": 70}
    as_filed = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"fat": 0.3})
    assert (
        prop_uc.DecideProposal(factory, alice).execute(as_filed.id, approve=True).proposed is None
    )
    same = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"fiber": 0.5})
    unchanged = prop_uc.DecideProposal(factory, alice).execute(
        same.id, approve=True, changes={"fiber": 0.5}
    )
    assert unchanged.proposed is None, "the same value is no correction"


def test_t_svc_310_proposals_are_found_by_their_one_off(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-310: `consumable_id` finds the proposal a pending one-off belongs to."""
    new = prop_uc.ProposeNewProduct(factory, agent).execute(
        products_uc.ProductInput(name="Oat bar", kcal=400)
    )
    prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"kcal": 70})
    found = prop_uc.ListProposals(factory, alice).execute(consumable_id=new.consumable_id)
    assert [p.id for p in found] == [new.id]
    assert prop_uc.ListProposals(factory, alice).execute(consumable_id=skyr) == []


def test_t_svc_312_an_amendment_that_changes_nothing_leaves_no_trace(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-312: the same values again neither keep an original nor write an audit entry."""
    filed = prop_uc.ProposeProductChange(factory, agent).execute(skyr, {"kcal": 70})
    same = prop_uc.AmendProposal(factory, alice).execute(filed.id, {"kcal": 70})
    assert same.proposed is None
    assert _audit(factory, alice, "product.proposal.amend") == []
