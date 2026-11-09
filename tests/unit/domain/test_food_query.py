"""T-DOM-215…217: searching a spoken food the way a person would (#78)."""

from __future__ import annotations

import pytest

from victus.domain.services import food_query as fq
from victus.domain.services import search_ranking as sr

pytestmark = pytest.mark.domain

#: A synthetic catalogue name of the kind the issue describes: brand, product, flour mix.
BREAD = "Bakery Valdrik Fitnessbrötchen (wheat 95 % / rye 5 %)"


def test_t_dom_215_quantities_units_and_fillers_are_not_searched() -> None:
    """T-DOM-215: amounts, units, number words and filler words leave the query; what is left
    is searched as a whole and word by word, and a text of nothing else keeps its words."""
    phrase = "110 g Fitnessbrötchen from Bakery Waldrik"
    assert fq.content_words(phrase) == ["fitnessbroetchen", "bakery", "waldrik"]
    assert fq.variants(phrase) == [
        phrase,
        "fitnessbroetchen bakery waldrik",
        "fitnessbroetchen",
        "bakery",
        "waldrik",
    ]
    assert fq.content_words("six thin slices of Brand Y cheese") == [
        "thin",
        "brand",
        "y",
        "cheese",
    ]
    assert fq.content_words("1 Stück, 2x Scheiben vom Käse") == ["kaese"]
    # nothing but a container word: it is what was asked for
    assert fq.content_words("Glas") == ["glas"]
    assert fq.variants("Skyr") == ["Skyr"]
    assert fq.variants("") == []
    assert fq.content_words("110 g") == []


def test_t_dom_216_relevance_covers_the_query_not_the_name() -> None:
    """T-DOM-216: a long name that holds the food's word and a near spelling of a misheard
    brand outscores names that hold only one word; compounds and near spellings count,
    a name without any word of the query is no hit, and a one-word query keeps the tiers."""
    rel = fq.Relevance("110 g Fitnessbrötchen from Bakery Waldrik")
    bread = rel.of(BREAD)
    assert bread is not None
    assert bread.matched == ("fitnessbroetchen", "bakery", "waldrik")
    assert bread.tier == sr.NAME_PREFIX, "the name begins with a word of the query"
    others = [rel.of(n) for n in ("Bakery Valdrik rye bread", "Fitness muesli", "Brötchen")]
    assert others[0] is not None and others[0].score < bread.score
    assert others[1] is None, "'fitness' alone is not a word of the query"
    assert others[2] is None, "'Brötchen' is not 'Fitnessbrötchen'"

    hyphenated = rel.of("Fitness-Brötchen")
    assert hyphenated is not None and hyphenated.matched == ("fitnessbroetchen",)
    assert fq.Relevance("Ei").of("Fleisch-Eintopf") is not None, "a plain syllable still hits"

    # the brand counts like the name, and alone it finds every product of the brand
    by_brand = fq.Relevance("Brand Y").of("Cheese slices", "Brand Y")
    assert by_brand is not None and by_brand.score == 0.9

    # one word: the score follows the search tiers, so the egg stays first
    egg = fq.Relevance("Ei")
    scores = {n: egg.of(n) for n in ("Ei", "Eiweißmilch", "Bio Ei", "Rührei")}
    ranked = sorted(scores, key=lambda n: -scores[n].score)  # type: ignore[union-attr]
    assert ranked == ["Ei", "Eiweißmilch", "Bio Ei", "Rührei"]
    assert fq.Relevance("").of("Ei") is None
    assert fq.Relevance("Skyr").of("Ei") is None


def test_t_dom_217_one_off_names_barcodes_and_the_same_food() -> None:
    """T-DOM-217: a one-off is named after the food, not the sentence; a barcode is read
    from the query; two names are one food when they fold to the same text."""
    assert fq.one_off_name("110 g Fitnessbrötchen from Bakery X") == (
        "Fitnessbrötchen from Bakery X"
    )
    assert fq.one_off_name("1 pack butter chicken") == "Butter chicken"
    assert fq.one_off_name("a bowl of salt and pepper crisps, about 40 g") == (
        "Bowl of salt and pepper crisps"
    )
    assert fq.one_off_name("2 x 30 g") == "2 x 30 g", "nothing but an amount keeps its text"
    assert fq.one_off_name(None) == ""

    assert fq.eans_in("2001234500018") == ["2001234500018"]
    assert fq.eans_in("2 001234 500018") == ["2001234500018"]
    assert fq.eans_in("frozen meal 20012345, 1 pack") == ["20012345"]
    assert fq.eans_in("110 g") == [] and fq.eans_in("12345") == []

    assert fq.same_food("Butter chicken (Brand Z)", "butter  chicken (brand z)")
    assert fq.same_food("Käsebrötchen", "Kaesebroetchen")
    assert not fq.same_food("Butter chicken", "Butter chicken korma")
    assert not fq.same_food("", "")
