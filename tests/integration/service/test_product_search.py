"""T-SVC-079…080, T-SVC-480: the catalogue search answers a short query, pages, and
finds a long name with umlauts by any word in it."""

from __future__ import annotations

import unicodedata

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
    """T-SVC-079: an umlaut the query folds to ASCII is found among the other products.

    The query is normalised to "oel"; a ``LIKE`` against the stored name never matched it,
    and the substring search now folds both sides the same way.
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


#: Long names of the kind a bakery label or a ready meal produces: the word searched for
#: sits behind a brand and in front of a long list of ingredients, and carries an umlaut.
LONG_NAMES = [
    "Bäckerei Beispiel Fitnessbrötchen (Weizen 95 % / Roggen 5 % mit Quark, Kürbiskerne, "
    "Leinsamen, Sonnenblumenkerne, Sesam)",
    "Bäckerei Beispiel Laugenbrezel (Weizen, Salz)",
    "Bäckerei Beispiel Roggenmischbrot (Scheibe, ca. 50 g)",
    "Bäckerei Andere Semmel",
    "Hähnchenbrust (roh)",
    "Bio Hähnchen-Schenkel mit Haut, gegrillt (ohne Knochen)",
    "Grillhähnchen (Keule, mit Haut, Imbiss, ca. 250 g ohne Knochen)",
    "Reispfanne mit Hähnchen, Paprika und Erdnusssauce (Fertiggericht, 450 g)",
    "Zucchini",
]


@pytest.mark.parametrize("query", ["Fitnessbrötchen", "brötchen", "Brotchen", "Broetchen"])
def test_a_long_name_is_found_by_a_word_with_an_umlaut(
    factory: UowFactory, alice: TenantContext, query: str
) -> None:
    """T-SVC-480: "ö", "oe" and "o" all find the roll, whose name is ten times the query."""
    made = _seed(factory, alice, [*EI_NAMES, *LONG_NAMES])

    hits = [p.id for p in uc.SearchProducts(factory, alice).execute(query, limit=15)]

    assert made[LONG_NAMES[0]] in hits
    if query.lower().startswith("b"):
        # "Bäckerei Brötchen" has the word itself, the long name only a syllable of it
        assert hits == [made["Bäckerei Brötchen"], made[LONG_NAMES[0]]]
    else:
        assert hits == [made[LONG_NAMES[0]]]


def test_a_decomposed_name_is_found_by_a_composed_query(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-480: a name stored decomposed (NFD) answers a query typed composed (NFC)."""
    name = unicodedata.normalize("NFD", "Bäckerei Beispiel Fitnessbrötchen (Kürbiskerne)")
    made = _seed(factory, alice, [name, "Zucchini"])

    for query in ("Fitnessbrötchen", "brötchen", "Brotchen", "Bäckerei Beispiel"):
        hits = uc.SearchProducts(factory, alice).execute(query, limit=15)
        assert [p.id for p in hits] == [made[name]], query


def test_every_product_of_a_brand_word_is_returned(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-480: the words of a bakery's name find all of its products and no other."""
    _seed(factory, alice, [*EI_NAMES, *LONG_NAMES])

    for query in ("Bäckerei Beispiel", "Backerei Beispiel", "baeckerei beispiel"):
        names = [p.name for p in uc.SearchProducts(factory, alice).execute(query, limit=15)]
        assert sorted(names) == sorted(LONG_NAMES[:3]), query


def test_every_product_holding_a_word_is_returned_whole_words_first(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-480: `Hähnchen` finds every name that holds it, long ones included.

    Before, only the two shortest names came back: the substring search missed every
    umlaut, and the fuzzy matcher scores against the length of the whole name.
    """
    _seed(factory, alice, [*EI_NAMES, *LONG_NAMES])

    for query in ("Hähnchen", "Haehnchen", "hahnchen"):
        names = [p.name for p in uc.SearchProducts(factory, alice).execute(query, limit=15)]
        assert names == [
            "Hähnchenbrust (roh)",
            "Bio Hähnchen-Schenkel mit Haut, gegrillt (ohne Knochen)",
            "Reispfanne mit Hähnchen, Paprika und Erdnusssauce (Fertiggericht, 450 g)",
            "Grillhähnchen (Keule, mit Haut, Imbiss, ca. 250 g ohne Knochen)",
        ], query


def test_the_egg_still_comes_first_beside_long_names(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-480: the umlaut spellings do not demote `Ei` (#17) behind its syllables."""
    _seed(factory, alice, [*EI_NAMES, *LONG_NAMES, "Ei"])

    hits = uc.SearchProducts(factory, alice).execute("Ei", limit=3)

    assert [p.name for p in hits] == ["Ei", "Eiweißmilch", "Bio Ei (Größe L)"]
