"""T-SVC-091…095, 102…108: portion operations by proposal, and what refuses them (R81).

ADR 0013 lets an actor without ``approve`` draft and a person decide. Adding a portion
had that road; correcting or removing one did not, so the only way to do either was to
hold the scope the gate exists to withhold.

The plan a reviewer decides on has to name every refusal, not only the two the database
produces. Four proposals asking for ``piece_s``…``piece_xl`` — the size of an egg written
where the unit belongs — came back with nothing wrong, and approving each of them failed
after the click (issue #25).
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


@pytest.fixture
def juice(factory: UowFactory, alice: TenantContext) -> int:
    """A product whose values are per 100 ml and that has no density; returns its id."""
    return (
        products_uc.CreateProduct(factory, alice)
        .execute(products_uc.ProductInput(name="Apple juice", reference_unit="ml", kcal=46))
        .id
    )


def _store(
    factory: UowFactory, ctx: TenantContext, proposal_id: str, entry: dict[str, object]
) -> None:
    """Put an entry into a stored proposal that the drafting side would have refused.

    Some refusals are unreachable through the door — a non-positive amount is turned away
    while drafting — but a row written before that check existed, or by hand, still has to
    be readable rather than approvable.
    """
    with factory(ctx) as uow:
        stored = uow.proposals.get(proposal_id)
        assert stored is not None
        stored.changes = {"portions": [entry]}
        uow.flush()
        uow.commit()


def test_t_svc_102_a_unit_that_is_not_a_unit_is_named_in_the_plan(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-102: the four egg sizes of issue #25 — blocked, with the real unit named."""
    for code in ("piece_s", "piece_m", "piece_l", "piece_xl"):
        proposal = prop_uc.add_or_propose_portion(
            factory, writer, skyr, {"unit_code": code, "label": f"egg {code}", "amount": 60}
        )
        assert isinstance(proposal, dto.ProductProposalView)
        blocked = proposal.portion_plan[0].blocked
        assert blocked is not None
        assert f"there is no unit '{code}'" in blocked
        assert "a size belongs in the portion's label" in blocked
        assert "did you mean 'piece'?" in blocked

        with pytest.raises(Conflict, match=f"there is no unit '{code}'"):
            prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)
        assert prop_uc.GetProposal(factory, alice).execute(proposal.id).status == "pending"

    assert [p.unit_code for p in _portions(factory, alice, skyr)] == ["tub"]


def test_t_svc_103_an_updates_unit_is_read_the_same_way(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-103: ``UpdatePortion`` writes ``unit_code`` too, so the same refusal applies."""
    tub_id, _ = twins
    proposal = prop_uc.update_or_propose_portion(factory, writer, tub_id, {"unit_code": "tub_xl"})
    assert isinstance(proposal, dto.ProductProposalView)
    blocked = proposal.portion_plan[0].blocked
    assert blocked is not None and "there is no unit 'tub_xl'" in blocked
    assert "did you mean 'tub'?" in blocked

    with pytest.raises(Conflict, match="there is no unit 'tub_xl'"):
        prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=True)
    assert next(p for p in _portions(factory, alice, skyr) if p.id == tub_id).unit_code == "tub"


def test_t_svc_104_an_amount_the_product_cannot_be_measured_in(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, juice: int
) -> None:
    """T-SVC-104: R75 refuses grams for a product stated per millilitre, until a density does."""
    in_kg = prop_uc.ProposeProductChange(factory, writer).execute(
        juice,
        {
            "portions": [
                {"unit_code": "bottle", "label": "bottle", "amount": 1, "amount_unit": "kg"}
            ]
        },
    )
    assert in_kg.portion_plan[0].blocked == "a portion's amount is in g or ml, not 'kg'"

    in_grams = prop_uc.add_or_propose_portion(
        factory,
        writer,
        juice,
        {"unit_code": "glass", "label": "glass", "amount": 250, "amount_unit": "g"},
    )
    assert isinstance(in_grams, dto.ProductProposalView)
    blocked = in_grams.portion_plan[0].blocked
    assert blocked is not None and "per 100 ml, so a portion must be in ml" in blocked
    assert "Set a density to allow g." in blocked
    with pytest.raises(Conflict, match="density"):
        prop_uc.DecideProposal(factory, alice).execute(in_grams.id, approve=True)

    # R75's way out, since 1.2.0: with a density the same proposal is applicable, and the
    # plan is read against the catalogue as it stands, not as it stood while drafting.
    products_uc.UpdateProduct(factory, alice).execute(juice, {"density_g_per_ml": 1.05})
    reread = prop_uc.GetProposal(factory, alice).execute(in_grams.id)
    assert reread.portion_plan[0].blocked is None
    prop_uc.DecideProposal(factory, alice).execute(in_grams.id, approve=True)
    assert [(p.unit_code, p.amount_unit) for p in _portions(factory, alice, juice)] == [
        ("glass", "g")
    ]


def test_t_svc_105_an_amount_that_is_not_an_amount(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-105: a portion needs a positive weight, whether it is added or corrected."""
    tub_id, _ = twins
    zero = prop_uc.update_or_propose_portion(factory, writer, tub_id, {"amount": 0})
    assert isinstance(zero, dto.ProductProposalView)
    assert zero.portion_plan[0].blocked == "a portion needs a positive amount"
    with pytest.raises(Conflict, match="positive amount"):
        prop_uc.DecideProposal(factory, alice).execute(zero.id, approve=True)

    text = prop_uc.update_or_propose_portion(factory, writer, tub_id, {"amount": "half a tub"})
    assert isinstance(text, dto.ProductProposalView)
    assert text.portion_plan[0].blocked == (
        "'half a tub' is not an amount; a portion needs a positive number"
    )

    # An add cannot reach the store with such an amount, but a row written by hand can.
    pending = prop_uc.add_or_propose_portion(
        factory, writer, skyr, {"unit_code": "slice", "label": "slice", "amount": 25}
    )
    assert isinstance(pending, dto.ProductProposalView)
    _store(
        factory,
        alice,
        pending.id,
        {"op": "add", "unit_code": "slice", "label": "slice", "amount": -25},
    )
    reread = prop_uc.GetProposal(factory, alice).execute(pending.id)
    assert reread.portion_plan[0].blocked == "a portion needs a positive amount"

    assert next(p for p in _portions(factory, alice, skyr) if p.id == tub_id).amount == 400


def test_t_svc_106_a_portion_id_that_is_not_this_ones(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    skyr: int,
    juice: int,
    twins: tuple[int, int],
) -> None:
    """T-SVC-106: the row is gone, or it never belonged here — two different reasons."""
    _, piece_id = twins
    elsewhere = products_uc.AddPortion(factory, alice).execute(
        juice,
        products_uc.PortionInput(unit_code="glass", label="glass", amount=250, amount_unit="ml"),
    )

    borrowed = prop_uc.ProposeProductChange(factory, writer).execute(
        skyr, {"portions": [{"op": "update", "portion_id": elsewhere.id, "amount": 300}]}
    )
    assert borrowed.portion_plan[0].blocked == (
        f"portion {elsewhere.id} belongs to product {juice}, not to this one"
    )

    removal = prop_uc.delete_or_propose_portion(
        factory, writer, piece_id, reason="a piece is not 400 g"
    )
    assert isinstance(removal, dto.ProductProposalView)
    assert removal.portion_plan[0].blocked is None
    products_uc.DeletePortion(factory, alice).execute(piece_id)  # a person got there first

    reread = prop_uc.GetProposal(factory, alice).execute(removal.id)
    assert reread.portion_plan[0].blocked == f"portion {piece_id} no longer exists"
    with pytest.raises(Conflict, match="no longer exists"):
        prop_uc.DecideProposal(factory, alice).execute(removal.id, approve=True)


def test_t_svc_107_an_entry_in_a_shape_no_use_case_accepts(
    factory: UowFactory,
    alice: TenantContext,
    writer: TenantContext,
    twins: tuple[int, int],
) -> None:
    """T-SVC-107: the structural refusals, reachable only from a row written by hand.

    These four were already refused *while deciding* — ``_validated_portions`` runs before
    anything is applied — so what was missing is only that the pending plan said so.
    """
    tub_id, _ = twins
    pending = prop_uc.update_or_propose_portion(factory, writer, tub_id, {"amount": 450})
    assert isinstance(pending, dto.ProductProposalView)

    cases = {
        "there is no portion operation 'replace'; use one of add, update, delete": {
            "op": "replace",
            "portion_id": tub_id,
            "amount": 450,
        },
        "a portion to update needs its portion_id": {"op": "update", "amount": 450},
        f"an update needs at least one of: {', '.join(prop_uc.PORTION_FIELDS)}": {
            "op": "update",
            "portion_id": tub_id,
        },
        "a portion to add needs a unit_code": {"op": "add", "label": "slice", "amount": 25},
    }
    for reason, entry in cases.items():
        _store(factory, alice, pending.id, entry)
        plan = prop_uc.GetProposal(factory, alice).execute(pending.id).portion_plan
        assert plan[0].blocked == reason
        with pytest.raises(ValidationFailed):
            prop_uc.DecideProposal(factory, alice).execute(pending.id, approve=True)


def test_t_svc_108_the_reference_a_portion_is_read_against_is_the_one_it_will_have(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-108: a proposal that moves the reference unit and adds a portion is one change.

    Approving writes the product's own fields before its portions, so reading a portion
    against the unit the product has *now* would refuse the half that is about to be legal
    and wave through the half that is about to be refused.
    """
    to_millilitres = prop_uc.ProposeProductChange(factory, writer).execute(
        skyr,
        {
            "reference_unit": "ml",
            "portions": [
                {"unit_code": "glass", "label": "glass", "amount": 200, "amount_unit": "ml"},
                {"unit_code": "cup", "label": "cup", "amount": 150, "amount_unit": "g"},
            ],
        },
    )
    fine, refused = to_millilitres.portion_plan
    assert fine.blocked is None, "millilitres, for a product that is about to be per 100 ml"
    assert refused.blocked is not None and "per 100 ml" in refused.blocked

    # A `new` proposal has no product row at all; the values it carries are the reference.
    proposed = prop_uc.ProposeNewProduct(factory, writer).execute(
        products_uc.ProductInput(name="Orange juice", reference_unit="ml", kcal=45),
        portions=[
            {"unit_code": "glass_l", "label": "large glass", "amount": 300, "amount_unit": "ml"},
            {"unit_code": "bottle", "label": "bottle", "amount": 1000, "amount_unit": "g"},
            {"unit_code": "glass", "label": "glass", "amount": 200, "amount_unit": "ml"},
        ],
    )
    unknown, in_grams, ok = proposed.portion_plan
    assert unknown.blocked is not None and "there is no unit 'glass_l'" in unknown.blocked
    assert in_grams.blocked is not None and "per 100 ml" in in_grams.blocked
    assert ok.blocked is None
