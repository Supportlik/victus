"""T-DOM-085: search relevance tiers — a word boundary beats an initial letter."""

from __future__ import annotations

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
