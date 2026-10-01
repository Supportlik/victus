"""T-SVC-417…424: product proposals at their edges — input checks, the plan, the decision."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import (
    SCOPE_READ,
    SCOPE_WRITE,
    ScopeError,
    TenantContext,
)
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service


@pytest.fixture
def writer(alice: TenantContext) -> TenantContext:
    return TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_w", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
    )


@pytest.fixture
def reader(alice: TenantContext) -> TenantContext:
    return TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_r", scopes=frozenset({SCOPE_READ})
    )


def test_t_svc_417_proposals_need_a_writing_scope(
    factory: UowFactory, reader: TenantContext, skyr: int
) -> None:
    """T-SVC-417: a read-only actor can propose no change, no product and no version; the
    refusal names ``agent:write``."""
    calls: list[Any] = [
        lambda: uc.ProposeProductChange(factory, reader).execute(skyr, {"kcal": 60}),
        lambda: uc.ProposeNewProduct(factory, reader).execute(
            products_uc.ProductInput(name="Kefir")
        ),
        lambda: uc.ProposeProductVersion(factory, reader).execute(
            skyr, date(2026, 5, 1), {"kcal": 60}
        ),
    ]
    for call in calls:
        with pytest.raises(ScopeError, match="agent:write"):
            call()


def test_t_svc_418_unknown_product_capture_and_twin_are_refused(
    factory: UowFactory, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-418: an unknown product or capture is 404 for every kind; a new product under a
    name the catalogue has is 409; a version day that is not a day is 422."""
    with pytest.raises(NotFound):
        uc.ProposeProductChange(factory, writer).execute(999_999, {"kcal": 1})
    with pytest.raises(NotFound, match="capture"):
        uc.ProposeProductChange(factory, writer).execute(skyr, {"kcal": 1}, capture_id="cap_none")
    with pytest.raises(Conflict, match="already exists"):
        uc.ProposeNewProduct(factory, writer).execute(products_uc.ProductInput(name="Skyr natural"))
    with pytest.raises(NotFound, match="capture"):
        uc.ProposeNewProduct(factory, writer).execute(
            products_uc.ProductInput(name="Kefir"), capture_id="cap_none"
        )
    with pytest.raises(NotFound):
        uc.ProposeProductVersion(factory, writer).execute(999_999, date(2026, 5, 1), {"kcal": 1})
    with pytest.raises(NotFound, match="capture"):
        uc.ProposeProductVersion(factory, writer).execute(
            skyr, date(2026, 5, 1), {"kcal": 1}, capture_id="cap_none"
        )
    with pytest.raises(ValidationFailed, match="YYYY-MM-DD"):
        uc.ProposeProductVersion(factory, writer).execute(skyr, "soon", {"kcal": 1})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("portions", "match"),
    [
        ({"unit_code": "tub"}, "list of objects"),
        (["tub"], "list of objects"),
        ([{"unit_code": "tub", "label": "tub"}], "positive amount"),
        ([{"unit_code": "tub", "amount": "lots"}], "positive amount"),
        ([{"unit_code": "tub", "amount": 0}], "positive amount"),
    ],
)
def test_t_svc_419_portion_entries_are_checked_before_they_are_stored(
    factory: UowFactory, writer: TenantContext, skyr: int, portions: Any, match: str
) -> None:
    """T-SVC-419: ``portions`` must be a list of objects, and an add needs a positive amount."""
    with pytest.raises(ValidationFailed, match=match):
        uc.ProposeProductChange(factory, writer).execute(skyr, {"portions": portions})


def test_t_svc_424_a_new_product_only_adds_portions(
    factory: UowFactory, writer: TenantContext
) -> None:
    """T-SVC-424: a product that does not exist yet has no portion to update or delete."""
    with pytest.raises(ValidationFailed, match="does not exist yet"):
        uc.ProposeNewProduct(factory, writer).execute(
            products_uc.ProductInput(name="Kefir"),
            portions=[{"op": "update", "portion_id": 1, "amount": 5}],
        )


def test_t_svc_420_the_plan_names_twins_and_impossible_operations(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-420: the plan of no list is empty, skips entries that are no objects, refuses an
    update without a product, a second add of the same pair, an add that twins a portion
    and an update that would twin another one."""
    tub = products_uc.GetProduct(factory, alice).execute(skyr).portions[0]
    cup = products_uc.AddPortion(factory, alice).execute(
        skyr, products_uc.PortionInput("cup", "cup", 150)
    )
    with factory(alice) as uow:
        assert uc.portion_plan(uow, skyr, "not a list") == []
        rows = uc.portion_plan(
            uow,
            skyr,
            [
                "skipped",
                {"op": "add", "unit_code": "glass", "label": "glass", "amount": 200},
                {"op": "add", "unit_code": "glass", "label": "glass", "amount": 210},
                {"op": "add", "unit_code": "tub", "label": "tub", "amount": 400},
                {"op": "update", "portion_id": cup.id, "unit_code": "tub", "label": "tub"},
            ],
        )
        assert [r.blocked is None for r in rows] == [True, False, False, False]
        assert "already adds" in (rows[1].blocked or "")
        assert f"portion {tub.id} already carries" in (rows[2].blocked or "")
        assert f"portion {tub.id} already carries" in (rows[3].blocked or "")
        orphan = uc.portion_plan(
            uow,
            None,
            [{"op": "delete", "portion_id": cup.id}],
            reference=uc._reference_of(None, {}),
        )
        assert "does not exist yet" in (orphan[0].blocked or "")


def test_t_svc_421_decision_field_selection_and_overrides(
    factory: UowFactory, alice: TenantContext, writer: TenantContext, skyr: int
) -> None:
    """T-SVC-421: a decision may pick only proposed fields, at least one of them, and may
    only override fields of its kind."""
    pr = uc.ProposeProductChange(factory, writer).execute(skyr, {"kcal": 64.0, "protein": 12.0})
    decide = uc.DecideProposal(factory, alice)
    with pytest.raises(ValidationFailed, match="not part of this proposal: fat"):
        decide.execute(pr.id, approve=True, fields=["fat"])
    with pytest.raises(ValidationFailed, match="at least one field"):
        decide.execute(pr.id, approve=True, fields=[])
    with pytest.raises(ValidationFailed, match="cannot be applied: valid_from"):
        decide.execute(pr.id, approve=True, changes={"valid_from": "2026-05-01"})
    done = decide.execute(pr.id, approve=True, fields=["kcal"])
    assert done.status == "approved"
    assert products_uc.GetProduct(factory, alice).execute(skyr).kcal == 64.0


def test_t_svc_422_promotion_keeps_the_name_and_refuses_a_late_twin(
    factory: UowFactory, alice: TenantContext, writer: TenantContext
) -> None:
    """T-SVC-422: approving a new product with a blank name override keeps the proposed
    name; one whose name the catalogue gained meanwhile is 409 and stays pending."""
    kefir = uc.ProposeNewProduct(factory, writer).execute(
        products_uc.ProductInput(name="Kefir", kcal=60)
    )
    done = uc.DecideProposal(factory, alice).execute(kefir.id, approve=True, changes={"name": "  "})
    assert done.status == "approved"
    assert products_uc.GetProduct(factory, alice).execute(done.product_id).name == "Kefir"  # type: ignore[arg-type]

    ayran = uc.ProposeNewProduct(factory, writer).execute(
        products_uc.ProductInput(name="Ayran", kcal=40)
    )
    products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Ayran", kcal=41)
    )
    with pytest.raises(Conflict, match="already exists"):
        uc.DecideProposal(factory, alice).execute(ayran.id, approve=True)


def test_t_svc_423_adapter_helpers_and_pending_count(
    factory: UowFactory, alice: TenantContext, writer: TenantContext
) -> None:
    """T-SVC-423: with ``approve`` a product is created with its portions; a portion change
    needs a field and a known portion; ``pending_count`` counts open proposals."""
    made = uc.create_or_propose_product(
        factory,
        alice,
        products_uc.ProductInput(name="Rice", kcal=350),
        portions=[{"unit_code": "cup", "label": "cup", "amount": 180}],
    )
    assert isinstance(made, uc.dto.ProductView)
    assert [p.label for p in products_uc.GetProduct(factory, alice).execute(made.id).portions] == [
        "cup"
    ]

    with pytest.raises(ValidationFailed, match="a portion change needs one of"):
        uc.update_or_propose_portion(factory, alice, 1, {"bogus": 1})
    with pytest.raises(NotFound, match="portion 999999"):
        uc.update_or_propose_portion(factory, writer, 999_999, {"amount": 5})

    uc.ProposeProductChange(factory, writer).execute(made.id, {"kcal": 351})
    with factory(alice) as uow:
        assert uc.pending_count(uow) == 1
