"""T-SVC-068…070: a product's values may change over time without rewriting old days (R70)."""

from __future__ import annotations

from datetime import date

import pytest

from victus.application.errors import Conflict, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import products as uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service


def test_a_new_version_closes_the_old_one_and_copies_the_rest(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-068: the previous version keeps its numbers and its days."""
    fresh = uc.NewProductVersion(factory, alice).execute(
        skyr, date(2026, 6, 1), {"kcal": 66, "source": "new label"}
    )
    assert fresh.id != skyr
    assert fresh.name == "Skyr natural"
    assert fresh.kcal == 66 and fresh.source == "new label"
    # untouched values come along, portions included
    assert fresh.protein == 11
    assert [(p.label, p.amount) for p in fresh.portions] == [("tub", 400)]
    assert fresh.valid_from == date(2026, 6, 1)
    assert fresh.valid_until is None, "the current version has no end"
    assert fresh.supersedes_id == skyr

    old = uc.GetProduct(factory, alice).execute(skyr)
    assert old.kcal == 63, "the old day's numbers must not change"
    assert old.valid_until == date(2026, 5, 31)

    both = uc.ProductVersions(factory, alice).execute(fresh.id)
    assert [p.id for p in both] == [skyr, fresh.id], "history reads oldest first, from either end"
    assert [p.id for p in uc.ProductVersions(factory, alice).execute(skyr)] == [skyr, fresh.id]


def test_search_returns_the_version_that_applied_on_the_day(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-069: without this a search would return every version as a separate hit."""
    fresh = uc.NewProductVersion(factory, alice).execute(skyr, date(2026, 6, 1), {"kcal": 66})

    # a day before the change resolves to the old row
    early = uc.SearchProducts(factory, alice).execute("skyr", on=date(2026, 5, 20))
    assert [(p.id, p.kcal) for p in early] == [(skyr, 63)]

    # the day itself, and any later day, resolve to the new one
    for day in (date(2026, 6, 1), date(2027, 1, 1)):
        later = uc.SearchProducts(factory, alice).execute("skyr", on=day)
        assert [(p.id, p.kcal) for p in later] == [(fresh.id, 66)]

    # without a day the current version wins, and only once
    current = uc.SearchProducts(factory, alice).execute("skyr")
    assert [p.id for p in current] == [fresh.id]


def test_a_third_version_and_the_guards(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-070: versions may chain, but not overlap or start before their predecessor."""
    second = uc.NewProductVersion(factory, alice).execute(skyr, date(2026, 6, 1), {"kcal": 66})
    third = uc.NewProductVersion(factory, alice).execute(second.id, date(2026, 9, 1), {"kcal": 70})
    assert uc.GetProduct(factory, alice).execute(second.id).valid_until == date(2026, 8, 31)
    assert [p.id for p in uc.ProductVersions(factory, alice).execute(skyr)] == [
        skyr,
        second.id,
        third.id,
    ]
    # every window resolves to exactly one version
    assert uc.SearchProducts(factory, alice).execute("skyr", on=date(2026, 7, 1))[0].id == second.id

    with pytest.raises(ValidationFailed):
        uc.NewProductVersion(factory, alice).execute(third.id, date(2026, 9, 1), {})
    with pytest.raises(Conflict):
        # the second version already has a successor covering that day
        uc.NewProductVersion(factory, alice).execute(second.id, date(2026, 10, 1), {})
