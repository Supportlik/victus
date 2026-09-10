"""T-SVC-079…080: the catalogue search answers a short query, and pages."""

from __future__ import annotations

import pytest

from victus.application.tenant_context import TenantContext
from victus.application.use_cases import products as uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service

#: Names that all contain "ei", sorted alphabetically around the product actually named
#: "Ei": a search that orders hits by name buries the answer among its syllables.
EI_NAMES = [
    "Bäckerei Brötchen",
    "Bio Ei (Größe L)",
    "Eiweißmilch",
    "Fleischwurst",
    "Hackfleisch",
    "Reiswaffeln",
    "Schinken (Scheiben)",
    "Weizenmehl",
    "Zucker (fein)",
]


def _seed(factory: UowFactory, ctx: TenantContext, names: list[str]) -> dict[str, int]:
    made = {}
    for name in names:
        made[name] = uc.CreateProduct(factory, ctx).execute(uc.ProductInput(name=name, kcal=100)).id
    return made


def test_the_named_product_comes_first_among_its_syllables(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-079: `Ei` finds the egg, though nine other names contain those letters."""
    _seed(factory, alice, [*EI_NAMES, "Ei"])

    hits = uc.SearchProducts(factory, alice).execute("Ei", limit=3)

    assert hits[0].name == "Ei", "the exact name must not sit behind a syllable hit"
    # the name that begins with the query, then the one whose second word does
    assert [p.name for p in hits] == ["Ei", "Eiweißmilch", "Bio Ei (Größe L)"]

    # the syllable hits are still there, just later, and alphabetical among themselves
    all_hits = [p.name for p in uc.SearchProducts(factory, alice).execute("Ei", limit=50)]
    assert set(all_hits) == {*EI_NAMES, "Ei"}
    assert all_hits[3:] == [
        "Bäckerei Brötchen",
        "Fleischwurst",
        "Hackfleisch",
        "Reiswaffeln",
        "Schinken (Scheiben)",
        "Weizenmehl",
        "Zucker (fein)",
    ]


def test_the_fuzzy_tier_contributes_when_sql_cannot_match(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-079: an umlaut the query folds to ASCII is beyond `LIKE`, so the matcher runs.

    The query is normalised to "oel" and the stored name is not, so the substring search
    returns nothing however many other products exist.
    """
    _seed(factory, alice, [*EI_NAMES, "Öl", "Ölsardinen"])

    hits = uc.SearchProducts(factory, alice).execute("Öl", limit=5)

    assert hits and hits[0].name == "Öl"


def test_a_page_at_a_time_reaches_the_whole_catalogue(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-080: without an offset everything past the first window was out of reach."""
    _seed(factory, alice, [f"Product {i:02d}" for i in range(25)])

    first = uc.SearchProducts(factory, alice).execute("", limit=10)
    second = uc.SearchProducts(factory, alice).execute("", limit=10, offset=10)
    last = uc.SearchProducts(factory, alice).execute("", limit=10, offset=20)

    assert [p.name for p in first] == [f"Product {i:02d}" for i in range(10)]
    assert [p.name for p in second] == [f"Product {i:02d}" for i in range(10, 20)]
    assert [p.name for p in last] == [f"Product {i:02d}" for i in range(20, 25)]
    assert len({p.id for p in [*first, *second, *last]}) == 25, "no row seen twice or skipped"
    assert uc.SearchProducts(factory, alice).execute("", limit=10, offset=25) == []


def test_a_search_pages_too(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-080: the offset applies to a query as well, on the ranked order."""
    _seed(factory, alice, [*EI_NAMES, "Ei"])

    ranked = [p.name for p in uc.SearchProducts(factory, alice).execute("Ei", limit=50)]
    paged = [
        p.name
        for offset in (0, 4, 8)
        for p in uc.SearchProducts(factory, alice).execute("Ei", limit=4, offset=offset)
    ]

    assert paged == ranked
