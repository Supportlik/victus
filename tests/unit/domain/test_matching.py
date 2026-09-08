"""T-DOM-020…023: three-tier consumable matching and its two regression traps."""

from __future__ import annotations

import pytest

from victus.domain.services.matching import ConsumableIndex, coverage, normalize, short_form
from victus.domain.values import ConsumableKind

pytestmark = pytest.mark.domain

P, R = ConsumableKind.PRODUCT, ConsumableKind.RECIPE_BATCH


@pytest.fixture
def index() -> ConsumableIndex:
    return ConsumableIndex(
        [
            (1, P, "Kartoffel (roh)"),
            (2, P, "Kartoffel (gekocht)"),
            (3, P, "Arla Skyr Natur"),
            (4, R, "Skyr-Beeren-Leinsamen"),
            (5, P, "Bergquell Vollkornbrot (750 g Laib)"),
            (6, P, "Vollmilch (3,5%)"),
            (7, R, "Chili sin Carne"),
            (8, P, "Chili sin Carne Gewürzmischung"),
        ]
    )


def test_normalize_keeps_parentheses_content() -> None:
    assert normalize("Kartoffel (roh gewogen)") == "kartoffel roh gewogen"
    assert normalize("Süßkartoffel **(TK)**") == "suesskartoffel tk"
    assert short_form("Kartoffel (roh gewogen)") == "kartoffel"


def test_tier1_exact_with_parentheses(index: ConsumableIndex) -> None:
    """T-DOM-020: raw and cooked potato are different products."""
    hits = index.find("Kartoffel (roh)")
    assert hits[0].consumable_id == 1 and hits[0].tier == 1 and hits[0].score == 1.0
    hits = index.find("kartoffel (GEKOCHT)")
    assert hits[0].consumable_id == 2 and hits[0].tier == 1


def test_tier2_requires_unique_short_form(index: ConsumableIndex) -> None:
    """T-DOM-021: 'Kartoffel' is ambiguous → no tier-2 hit, only fuzzy candidates."""
    hits = index.find("Kartoffel")
    assert all(h.tier == 3 for h in hits)
    assert {h.consumable_id for h in hits} <= {1, 2}
    # unique short form → tier 2
    hits = index.find("Bergquell Vollkornbrot")
    assert hits[0].consumable_id == 5 and hits[0].tier == 2 and hits[0].score == 0.95


def test_substring_trap(index: ConsumableIndex) -> None:
    """T-DOM-022: an ingredient must not match a recipe that merely contains its name."""
    hits = index.find("Leinsamen (geschrotet)")
    assert all(h.kind is not R for h in hits)
    assert index.best("Leinsamen (geschrotet)") is None


def test_threshold_boundary() -> None:
    """T-DOM-023: coverage 0.61 fails, 0.62 passes (products)."""
    assert coverage("abcde", "abcdefgh") == pytest.approx(0.625)
    idx = ConsumableIndex([(1, P, "abcdefgh"), (2, P, "abcdefghijklm")])
    hits = idx.find("abcde")
    assert [h.consumable_id for h in hits] == [1]  # 5/13 = 0.38 fails
    assert hits[0].tier == 3 and hits[0].score == pytest.approx(0.625)
    assert coverage("abcde", "abcdefghi") < 0.62 and idx.find("abcd") == []


def test_fuzzy_token_match_reordered_words(index: ConsumableIndex) -> None:
    hits = index.find("Skyr Natur (Arla)")
    assert hits[0].consumable_id == 3 and hits[0].tier == 3 and hits[0].score == 1.0


def test_recipe_threshold_is_stricter(index: ConsumableIndex) -> None:
    # "chili sin carne" vs recipe "chili sin carne": exact → tier 1
    best = index.best("Chili sin Carne")
    assert best is not None and best.kind is R and best.tier == 1
    # partial recipe name below 0.75 → no recipe candidate
    assert all(h.kind is not R for h in index.find("Chili"))


def test_best_prefers_recipe_when_both_qualify(index: ConsumableIndex) -> None:
    best = index.best("chili sin carne (Meal Prep)")
    assert best is not None and best.consumable_id == 7


def test_scores_monotone_and_limited(index: ConsumableIndex) -> None:
    hits = index.find("Kartoffel", limit=1)
    assert len(hits) <= 1
    hits = index.find("Skyr")
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_empty_and_short_inputs(index: ConsumableIndex) -> None:
    assert index.find("") == []
    assert index.find(None) == []
    assert index.best("   ") is None
