"""T-SVC-073…078: without ``approve`` an actor proposes, it never states a fact (R81)."""

from __future__ import annotations

from datetime import date

import pytest

from victus.application import dto
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
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

DAY = date(2026, 3, 11)
AGENT_SCOPES = frozenset(
    {SCOPE_READ, SCOPE_WRITE, SCOPE_CAPTURE_READ, SCOPE_CAPTURE_WRITE, SCOPE_AGENT_WRITE}
)


@pytest.fixture
def agent(alice: TenantContext) -> TenantContext:
    """The scopes an agent token holds: everything but ``approve``."""
    return TenantContext(tenant_id=alice.tenant_id, token_id="tok_agent", scopes=AGENT_SCOPES)


def _day(factory: UowFactory, ctx: TenantContext) -> int:
    day_uc.CreateDay(factory, ctx).execute(DAY, reliable=True, training_type="rest")
    return day_uc.AddMeal(factory, ctx).execute(DAY, "Dinner").id


def test_t_svc_073_written_item_is_a_draft(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-073: an actor without approve adds items as drafts, never as facts."""
    meal = _day(factory, alice)
    mine = day_uc.AddLineItem(factory, alice).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    theirs = day_uc.AddLineItem(factory, agent).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=200, unit_code="g")
    )
    assert mine.is_draft is False
    assert theirs.is_draft is True


def test_t_svc_074_approved_data_is_out_of_reach(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-074: write may not change or delete what a person approved."""
    meal = _day(factory, alice)
    fact = day_uc.AddLineItem(factory, alice).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    with pytest.raises(ScopeError):
        day_uc.UpdateLineItem(factory, agent).execute(fact.id, {"amount": 500})
    with pytest.raises(ScopeError):
        day_uc.DeleteLineItem(factory, agent).execute(fact.id)
    with pytest.raises(ScopeError):
        day_uc.CloseDay(factory, agent).execute(DAY)
    with pytest.raises(ScopeError):
        day_uc.UpdateDayFlags(factory, agent).execute(DAY, {"reliable": False})
    assert day_uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0].amount == 100


def test_t_svc_075_agent_may_withdraw_its_own_draft(
    factory: UowFactory, alice: TenantContext, agent: TenantContext, skyr: int
) -> None:
    """T-SVC-075: a draft is a proposal — its author may take it back, write alone may not."""
    meal = _day(factory, alice)
    draft = day_uc.AddLineItem(factory, agent).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=200, unit_code="g")
    )
    writer = TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_write", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
    )
    with pytest.raises(ScopeError):
        day_uc.DeleteLineItem(factory, writer).execute(draft.id)
    day_uc.DeleteLineItem(factory, agent).execute(draft.id)
    assert day_uc.GetDay(factory, alice).execute(DAY).meals[0].line_items == []


def test_t_svc_076_new_product_is_a_proposal(
    factory: UowFactory, alice: TenantContext, agent: TenantContext
) -> None:
    """T-SVC-076: product_create without approve files a proposal and a loggable one-off."""
    view = prop_uc.create_or_propose_product(
        factory,
        agent,
        products_uc.ProductInput(name="Oat drink barista", kcal=59, protein=1.3, fat=3.0),
        portions=[{"unit_code": "cup", "amount": 200.0, "is_default": True}],
        rationale="carton label",
    )
    assert isinstance(view, dto.ProductProposalView) and view.kind == "new"
    assert view.status == "pending" and view.product_id is None and view.consumable_id is not None
    assert products_uc.SearchProducts(factory, alice).execute("Oat drink") == []
    with pytest.raises(ScopeError):
        products_uc.CreateProduct(factory, agent).execute(
            products_uc.ProductInput(name="Oat drink plain", kcal=45)
        )


def test_t_svc_077_approving_promotes_the_one_off_in_place(
    factory: UowFactory, alice: TenantContext, agent: TenantContext
) -> None:
    """T-SVC-077: approval turns the one-off into the catalogue entry, keeping the meal."""
    proposal = prop_uc.ProposeNewProduct(factory, agent).execute(
        products_uc.ProductInput(
            name="Oat drink barista", kcal=59, protein=1.3, fat=3.0, source="carton"
        ),
        portions=[{"unit_code": "cup", "amount": 200.0, "is_default": True}],
    )
    consumable_id = proposal.consumable_id
    assert consumable_id is not None
    meal = _day(factory, alice)
    item = day_uc.AddLineItem(factory, agent).execute(
        meal, day_uc.LineItemInput(consumable_id=consumable_id, amount=250, unit_code="ml")
    )

    decided = prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)

    assert decided.status == "approved" and decided.product_id == consumable_id
    product = products_uc.GetProduct(factory, alice).execute(consumable_id)
    assert product.kcal == 59 and product.verified is True and product.source == "carton"
    assert [p.unit_code for p in product.portions] == ["cup"]
    assert [p.id for p in products_uc.SearchProducts(factory, alice).execute("Oat drink")] == [
        consumable_id
    ]
    kept = day_uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0]
    assert kept.id == item.id and kept.consumable_id == consumable_id and kept.is_draft is True


def test_t_svc_078_rejecting_keeps_the_meal_and_the_catalogue_clean(
    factory: UowFactory, alice: TenantContext, agent: TenantContext
) -> None:
    """T-SVC-078: a rejected product leaves the logged food alone; approve stays a decision."""
    proposal = prop_uc.ProposeNewProduct(factory, agent).execute(
        products_uc.ProductInput(name="Canteen goulash", kcal=140, protein=9)
    )
    assert proposal.consumable_id is not None
    meal = _day(factory, alice)
    day_uc.AddLineItem(factory, agent).execute(
        meal, day_uc.LineItemInput(consumable_id=proposal.consumable_id, amount=300, unit_code="g")
    )
    with pytest.raises(ScopeError):  # the agent must not decide its own proposal
        prop_uc.DecideProposal(factory, agent).execute(proposal.id, approve=True)

    prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=False)

    assert products_uc.SearchProducts(factory, alice).execute("goulash") == []
    day = day_uc.GetDay(factory, alice).execute(DAY)
    assert day.meals[0].line_items[0].kcal == pytest.approx(420.0)
    draft_uc.DiscardDraft(factory, alice).execute(DAY)
