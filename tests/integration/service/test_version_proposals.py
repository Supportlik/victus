"""T-SVC-096…101: "the recipe changed on this date" can be drafted, not only decided (R70, R81).

``NewProductVersion`` requires ``approve``, which is right about the decision and was
wrong about the drafting: an actor that read a changed label could only propose a
correction to the current version, and that rewrites what every day before the change
already counted. ADR 0013 asks for the drafting surface to be as wide as the deciding one.
"""

from __future__ import annotations

from datetime import date

import pytest

from victus.application import dto
from victus.application.errors import Conflict, ValidationFailed
from victus.application.tenant_context import (
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeError,
    TenantContext,
)
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service

#: A day that was eaten and counted before the label changed, and the day it changed.
BEFORE = date(2026, 5, 20)
CHANGED = date(2026, 6, 1)


@pytest.fixture
def writer(alice: TenantContext) -> TenantContext:
    """An actor that may write and propose, and may decide nothing."""
    return TenantContext(
        tenant_id=alice.tenant_id,
        token_id="tok_write",
        scopes=frozenset({SCOPE_READ, SCOPE_WRITE}),
    )


def _chain(factory: UowFactory, ctx: TenantContext, product_id: int) -> list[dto.ProductView]:
    return list(products_uc.ProductVersions(factory, ctx).execute(product_id))


def test_t_svc_096_write_proposes_a_version_instead_of_opening_one(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-096: the same door, a pending proposal, and a catalogue that has not moved."""
    with pytest.raises(ScopeError):  # the direct road is still a decision
        products_uc.NewProductVersion(factory, writer).execute(skyr, CHANGED, {"kcal": 66})

    proposal = prop_uc.version_or_propose_product_version(
        factory, writer, skyr, CHANGED, {"kcal": 66, "protein": 12}, rationale="the new label"
    )

    assert isinstance(proposal, dto.ProductProposalView)
    assert proposal.kind == "version" and proposal.status == "pending"
    assert proposal.product_id == skyr, "the version it revises, not one it created"
    assert proposal.changes == {"kcal": 66, "protein": 12, "valid_from": "2026-06-01"}
    assert proposal.current["kcal"] == 63, "what the reviewer compares against"
    assert proposal.rationale == "the new label"

    assert [p.id for p in _chain(factory, alice, skyr)] == [skyr]
    assert products_uc.GetProduct(factory, alice).execute(skyr).kcal == 63


def test_t_svc_097_approving_opens_the_version_and_the_earlier_days_keep_their_numbers(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-097: this is the whole point — a correction would have rewritten this day."""
    day_uc.CreateDay(factory, alice).execute(BEFORE, reliable=True, training_type="rest")
    meal = day_uc.AddMeal(factory, alice).execute(BEFORE, "Breakfast").id
    day_uc.AddLineItem(factory, alice).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="tub")
    )
    assert day_uc.GetDay(factory, alice).execute(BEFORE).macros.kcal == 252  # 63 × 400 / 100

    proposal = prop_uc.version_or_propose_product_version(
        factory, writer, skyr, CHANGED, {"kcal": 66, "source": "new label"}
    )
    assert isinstance(proposal, dto.ProductProposalView)
    decided = prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)
    assert decided.status == "approved"

    old, fresh = _chain(factory, alice, skyr)
    assert old.id == skyr and old.kcal == 63 and old.valid_until == date(2026, 5, 31)
    assert fresh.kcal == 66 and fresh.source == "new label"
    assert fresh.valid_from == CHANGED and fresh.valid_until is None
    assert fresh.supersedes_id == skyr and fresh.verified is True
    assert fresh.protein == 11, "untouched values come along"
    assert [(p.label, p.amount) for p in fresh.portions] == [("tub", 400)]

    assert day_uc.GetDay(factory, alice).execute(BEFORE).macros.kcal == 252
    assert products_uc.SearchProducts(factory, alice).execute("skyr", on=BEFORE)[0].id == skyr
    assert products_uc.SearchProducts(factory, alice).execute("skyr")[0].id == fresh.id


def test_t_svc_098_the_drafting_refuses_what_the_approval_could_not_do(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-098: a proposal nobody can approve is worse than a refusal at the door."""
    with pytest.raises(ValidationFailed):  # a version's portions come from its predecessor
        prop_uc.version_or_propose_product_version(
            factory,
            writer,
            skyr,
            CHANGED,
            {"portions": [{"unit_code": "cup", "label": "cup", "amount": 200}]},
        )
    with pytest.raises(ValidationFailed):
        prop_uc.version_or_propose_product_version(factory, writer, skyr, CHANGED, {})

    second = products_uc.NewProductVersion(factory, alice).execute(skyr, CHANGED, {"kcal": 66})
    with pytest.raises(ValidationFailed):  # not after the version it would replace
        prop_uc.version_or_propose_product_version(
            factory, writer, second.id, CHANGED, {"kcal": 70}
        )
    with pytest.raises(Conflict):  # that version already has a successor
        prop_uc.version_or_propose_product_version(
            factory, writer, skyr, date(2026, 7, 1), {"kcal": 70}
        )
    assert [p.id for p in _chain(factory, alice, skyr)] == [skyr, second.id]


def test_t_svc_099_approve_opens_the_version_directly_and_an_update_still_updates(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-099: one door, two branches — and the older two kinds are unchanged."""
    opened = prop_uc.version_or_propose_product_version(factory, alice, skyr, CHANGED, {"kcal": 66})
    assert isinstance(opened, dto.ProductView), "with approve nothing waits for review"
    assert opened.valid_from == CHANGED and opened.supersedes_id == skyr

    # An `update` proposal against the same product is still a correction in place: same
    # id, no new row. That contrast is what the `version` kind exists for.
    correction = prop_uc.update_or_propose_product(factory, writer, opened.id, {"kcal": 67})
    assert isinstance(correction, dto.ProductProposalView) and correction.kind == "update"
    prop_uc.DecideProposal(factory, alice).execute(correction.id, approve=True)

    chain = _chain(factory, alice, skyr)
    assert [(p.id, p.kcal) for p in chain] == [(skyr, 63), (opened.id, 67)]


def test_t_svc_100_a_version_proposal_the_chain_outgrew_is_refused_and_stays_pending(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-100: read again before the status flips, or the refusal loses the proposal."""
    proposal = prop_uc.version_or_propose_product_version(
        factory, writer, skyr, date(2026, 7, 1), {"kcal": 66}
    )
    assert isinstance(proposal, dto.ProductProposalView)

    # a person opens the version by hand while the proposal waits
    second = products_uc.NewProductVersion(factory, alice).execute(skyr, CHANGED, {"kcal": 65})

    with pytest.raises(Conflict) as refused:
        prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)
    assert "already replaced" in str(refused.value)
    assert prop_uc.GetProposal(factory, alice).execute(proposal.id).status == "pending"
    assert [p.id for p in _chain(factory, alice, skyr)] == [skyr, second.id]

    # rejecting it leaves the catalogue exactly as the person left it
    rejected = prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=False)
    assert rejected.status == "rejected"
    assert [p.id for p in _chain(factory, alice, skyr)] == [skyr, second.id]


def test_t_svc_101_approving_part_of_a_version_proposal_keeps_its_day(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-101: `valid_from` is the day the version starts, not a value under review."""
    proposal = prop_uc.version_or_propose_product_version(
        factory, writer, skyr, CHANGED, {"kcal": 66, "protein": 12}
    )
    assert isinstance(proposal, dto.ProductProposalView)

    prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True, fields=["kcal"])

    old, fresh = _chain(factory, alice, skyr)
    assert fresh.valid_from == CHANGED, "the day survives a reviewer picking values"
    assert (fresh.kcal, fresh.protein) == (66, 11), "the field left out keeps the old value"
    assert old.valid_until == date(2026, 5, 31)
