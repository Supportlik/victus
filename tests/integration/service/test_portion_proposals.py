"""T-SVC-091…095: a portion can be corrected or removed by proposal, not only added (R81).

ADR 0013 lets an actor without ``approve`` draft and a person decide. Adding a portion
had that road; correcting or removing one did not, so the only way to do either was to
hold the scope the gate exists to withhold.
"""

from __future__ import annotations

from datetime import date

import pytest

from victus.application import dto
from victus.application.errors import Conflict
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

DAY = date(2026, 3, 14)


@pytest.fixture
def writer(alice: TenantContext) -> TenantContext:
    """An actor that may write and propose, and may decide nothing."""
    return TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_write", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
    )


def _portions(factory: UowFactory, ctx: TenantContext, product_id: int) -> list[dto.PortionView]:
    return list(products_uc.GetProduct(factory, ctx).execute(product_id).portions)


@pytest.fixture
def twins(factory: UowFactory, alice: TenantContext, skyr: int) -> tuple[int, int]:
    """The 400 g tub, plus a "piece" of the same tub — the duplicate to be cleaned up."""
    piece = products_uc.AddPortion(factory, alice).execute(
        skyr, products_uc.PortionInput(unit_code="piece", label="piece", amount=400)
    )
    tub = next(p for p in _portions(factory, alice, skyr) if p.unit_code == "tub")
    return tub.id, piece.id


def test_t_svc_091_write_may_propose_an_update_and_a_delete(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-091: both become pending proposals, and the catalogue stays as it was."""
    tub_id, piece_id = twins
    with pytest.raises(ScopeError):  # the direct road is still a decision
        products_uc.UpdatePortion(factory, writer).execute(tub_id, {"label": "big tub"})
    with pytest.raises(ScopeError):
        products_uc.DeletePortion(factory, writer).execute(piece_id)

    corrected = prop_uc.update_or_propose_portion(
        factory, writer, tub_id, {"label": "big tub", "amount": 450}, rationale="lid says 450 g"
    )
    removed = prop_uc.delete_or_propose_portion(
        factory, writer, piece_id, reason="duplicates the tub of the same size"
    )

    assert isinstance(corrected, dto.ProductProposalView) and corrected.status == "pending"
    assert corrected.changes["portions"] == [
        {"op": "update", "portion_id": tub_id, "label": "big tub", "amount": 450}
    ]
    plan = corrected.portion_plan[0]
    assert plan.op == "update" and plan.blocked is None
    assert plan.current is not None and plan.current.amount == 400  # what it replaces

    assert isinstance(removed, dto.ProductProposalView)
    assert removed.changes["portions"] == [
        {"op": "delete", "portion_id": piece_id, "reason": "duplicates the tub of the same size"}
    ]
    gone = removed.portion_plan[0]
    assert gone.op == "delete" and gone.blocked is None and gone.used_by == 0
    assert gone.reason == "duplicates the tub of the same size"

    unchanged = _portions(factory, alice, skyr)
    assert {p.id for p in unchanged} == {tub_id, piece_id}
    assert next(p for p in unchanged if p.id == tub_id).label == "tub"


def test_t_svc_092_approval_applies_exactly_the_proposed_operations(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-092: the wrong row is corrected in place and the duplicate is gone — no third row."""
    tub_id, piece_id = twins
    corrected = prop_uc.update_or_propose_portion(
        factory, writer, piece_id, {"unit_code": "tub", "label": "tub 400"}
    )
    removed = prop_uc.delete_or_propose_portion(factory, writer, tub_id, reason="wrong label")
    assert isinstance(corrected, dto.ProductProposalView)
    assert isinstance(removed, dto.ProductProposalView)

    prop_uc.DecideProposal(factory, alice).execute(corrected.id, approve=True)
    prop_uc.DecideProposal(factory, alice).execute(removed.id, approve=True)

    left = _portions(factory, alice, skyr)
    assert [(p.id, p.unit_code, p.label, p.amount) for p in left] == [
        (piece_id, "tub", "tub 400", 400)
    ]
    assert products_uc.GetProduct(factory, alice).execute(skyr).verified is True


def test_t_svc_093_a_portion_entry_without_an_op_still_adds(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-093: proposals stored before the operations existed approve as they did."""
    pending = prop_uc.ProposeProductChange(factory, writer).execute(
        skyr, {"portions": [{"unit_code": "slice", "label": "slice", "amount": 25}]}
    )
    with factory(alice) as uow:  # rewrite the row the way it was stored back then
        stored = uow.proposals.get(pending.id)
        assert stored is not None
        stored.changes = {"portions": [{"unit_code": "slice", "label": "slice", "amount": 25}]}
        uow.flush()
        uow.commit()

    prop_uc.DecideProposal(factory, alice).execute(pending.id, approve=True)

    added = _portions(factory, alice, skyr)
    assert [(p.unit_code, p.amount) for p in added] == [("tub", 400), ("slice", 25)]


def test_t_svc_094_a_portion_in_use_cannot_be_removed_and_says_so_first(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-094: the refusal is on the pending proposal, not an error after the approval."""
    tub_id, _ = twins
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    meal = day_uc.AddMeal(factory, alice).execute(DAY, "Breakfast").id
    day_uc.AddLineItem(factory, alice).execute(
        meal, day_uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="tub")
    )

    proposal = prop_uc.delete_or_propose_portion(factory, writer, tub_id, reason="not a real size")
    assert isinstance(proposal, dto.ProductProposalView)
    blocked = proposal.portion_plan[0]
    assert blocked.used_by == 1
    assert blocked.blocked == "still used by 1 logged item, so it cannot be removed"

    with pytest.raises(Conflict) as refused:
        prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)
    assert "still used by 1 logged item" in str(refused.value)

    assert prop_uc.GetProposal(factory, alice).execute(proposal.id).status == "pending"
    assert tub_id in {p.id for p in _portions(factory, alice, skyr)}


def test_t_svc_095_a_swap_in_one_proposal_is_not_a_duplicate(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-095: the plan reads in the order it applies, so the row removed first is gone."""
    _, piece_id = twins
    proposal = prop_uc.ProposeProductChange(factory, writer).execute(
        skyr,
        {
            "portions": [
                {"op": "delete", "portion_id": piece_id, "reason": "a piece is not 400 g"},
                {"op": "add", "unit_code": "piece", "label": "piece", "amount": 100},
            ]
        },
    )
    assert [row.blocked for row in proposal.portion_plan] == [None, None]

    prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)

    left = _portions(factory, alice, skyr)
    assert [(p.unit_code, p.amount) for p in left] == [("tub", 400), ("piece", 100)]
