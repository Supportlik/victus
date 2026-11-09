"""T-DOM-085, T-DOM-088: search relevance tiers — a word boundary beats an initial letter."""

from __future__ import annotations

import unicodedata

import pytest

from victus.domain.services import search_ranking as sr

pytestmark = pytest.mark.domain


def test_the_tiers_of_a_two_letter_query() -> None:
    """`Ei` is a word, a first word, a later word and a syllable, in that order."""
    assert sr.name_rank("Ei", "Ei (Hühnerei)") == sr.NAME_PREFIX
    assert sr.name_rank("Ei", "Ei") == sr.EXACT
    assert sr.name_rank("Ei", "Eiweißmilch") == sr.NAME_PREFIX
    assert sr.name_rank("Ei", "Bio Ei") == sr.WORD_PREFIX
    assert sr.name_rank("Ei", "Rührei") == sr.SUBSTRING
    assert sr.name_rank("Ei", "Weizenmehl") == sr.SUBSTRING
    assert sr.name_rank("Ei", "Skyr natural") == sr.UNRANKED


def test_accents_and_case_do_not_decide_the_tier() -> None:
    """The exact answer must not be demoted for being spelled with an umlaut."""
    assert sr.name_rank("öl", "Öl") == sr.EXACT
    assert sr.name_rank("OEL", "Öl") == sr.EXACT
    assert sr.name_rank("Ei", "EI (GRÖSSE L)") == sr.NAME_PREFIX


def test_a_brand_hit_ranks_below_every_name_hit() -> None:
    assert sr.name_rank("arla", "Skyr natural", "Arla") == sr.BRAND
    assert sr.name_rank("arla", "Arla Skyr", "Arla") == sr.NAME_PREFIX
    assert sr.name_rank("arla", "Skyr natural", None) == sr.UNRANKED


def test_a_multi_word_query_still_prefixes() -> None:
    assert sr.name_rank("skyr nat", "Skyr natural") == sr.NAME_PREFIX
    assert sr.name_rank("skyr natural", "Skyr natural") == sr.EXACT


def test_sorting_puts_the_named_product_first() -> None:
    """The bug this ranking exists for: alphabetical order hides the answer."""
    names = ["Weizenmehl", "Reis", "Rührei", "Bio Ei", "Eiweißmilch", "Ei", "Fleischwurst"]
    assert sorted(names, key=lambda n: sr.sort_key("Ei", n)) == [
        "Ei",
        "Eiweißmilch",
        "Bio Ei",
        "Fleischwurst",
        "Reis",
        "Rührei",
        "Weizenmehl",
    ]


def test_an_empty_query_ranks_nothing() -> None:
    assert sr.name_rank("", "Ei") == sr.UNRANKED
    assert sr.name_rank("   ", "Ei") == sr.UNRANKED


#: A long name of the kind a bakery label produces: the word searched for sits in the
#: middle, the name is many times longer than the query, and it carries umlauts.
LONG_ROLL = (
    "Bakery Example Fitnessbrötchen (Weizen 95 % / Roggen 5 % mit Quark, "
    "Kürbis-, Lein- & Sonnenblumenkerne, Sesam)"
)


@pytest.mark.parametrize(
    ("query", "tier"),
    [
        ("Fitnessbrötchen", sr.WORD_PREFIX),
        ("fitnessbrotchen", sr.WORD_PREFIX),
        ("brötchen", sr.SUBSTRING),
        ("Brotchen", sr.SUBSTRING),
        ("Broetchen", sr.SUBSTRING),
    ],
)
def test_an_umlaut_matches_in_every_spelling(query: str, tier: int) -> None:
    """T-DOM-088: "ö", "oe" and "o" are one letter to the search, however long the name."""
    assert sr.matches(query, LONG_ROLL)
    assert sr.name_rank(query, LONG_ROLL) == tier


def test_a_decomposed_name_matches_a_composed_query() -> None:
    """T-DOM-088: "ö" stored as "o" + combining diaeresis (NFD) is the same letter."""
    decomposed = unicodedata.normalize("NFD", LONG_ROLL)
    assert decomposed != LONG_ROLL
    for query in ("brötchen", "Broetchen", unicodedata.normalize("NFD", "Brötchen")):
        assert sr.matches(query, decomposed), query
    assert sr.name_rank("Fitnessbrötchen", decomposed) == sr.WORD_PREFIX
    assert sr.name_rank("Kürbis", decomposed) == sr.WORD_PREFIX


def test_every_word_must_be_found_in_name_or_brand() -> None:
    """T-DOM-088: words are matched one by one, so their order does not matter."""
    assert sr.matches("Bakery Example", LONG_ROLL)
    assert sr.matches("sesam bakery", LONG_ROLL)
    assert sr.matches("skyr arla", "Skyr natural", "Arla")
    assert not sr.matches("Bakery Other", LONG_ROLL)
    assert not sr.matches("Hähnchen", LONG_ROLL)
    assert sr.matches("", LONG_ROLL), "a query without a word matches every row"
    assert sr.matches(" %% ", LONG_ROLL)


def test_a_whole_word_ranks_before_a_syllable_and_a_fuzzy_hit() -> None:
    """T-DOM-088: `Hähnchen` in any spelling, at the start, later on, or inside a word."""
    names = [
        "Zucchini",
        "Grillhähnchen (Keule)",
        "Bio Hähnchen-Schenkel mit Haut",
        "Hähnchenbrust (roh)",
        "Hahnchen",
    ]
    for query in ("Hähnchen", "haehnchen", "Hahnchen"):
        assert sorted(names, key=lambda n: sr.sort_key(query, n)) == [
            "Hahnchen",
            "Hähnchenbrust (roh)",
            "Bio Hähnchen-Schenkel mit Haut",
            "Grillhähnchen (Keule)",
            "Zucchini",
        ], query
