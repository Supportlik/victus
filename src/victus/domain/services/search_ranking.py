"""Relevance order for a search over consumable names.

The catalogue is searched with substrings, and in German a short word is also a syllable:
`ei` sits inside "Weizen", "Reis", "Fleisch" and "Bäckerei". Ordering those hits by name
puts the product actually called "Ei" wherever its initial letter happens to fall — past
the end of any result window — while every row above it is a false positive.

What separates the two is a word boundary, so that is what the tiers below are built on:
the whole name, then the name's beginning, then the beginning of a later word, and only
then a syllable buried anywhere. A brand hit comes after those, because the query was
typed into a field that lists names. Ties inside a tier are left to the caller, which
sorts them by name.

Both sides are compared in two spellings: :func:`~victus.domain.services.matching.normalize`
("ö" → "oe") and :func:`~victus.domain.services.matching.fold` ("ö", "oe" and "o" alike),
and a row takes the better tier of the two. Which rows are hits at all is decided here too
(:func:`matches`), and not by SQL: ``LIKE`` compares the query, folded to ASCII, with the
stored name, which is not — so every name with an umlaut was beyond reach of the substring
search, and only the fuzzy matcher, which scores against the length of the whole name,
could still find the short ones.
"""

from __future__ import annotations

from victus.domain.services.matching import fold, normalize

#: The whole name is what was typed.
EXACT = 0
#: The name begins with the query: "Ei (Größe L)", "Eiweißmilch" for `Ei`.
NAME_PREFIX = 1
#: A later word begins with the query: "Bio Ei" for `Ei`.
WORD_PREFIX = 2
#: The query is a syllable somewhere in the name: "Rührei", "Weizen" for `Ei`.
SUBSTRING = 3
#: Only the brand matches, which is how a search for "Arla" finds its products.
BRAND = 4
#: No literal hit at all; a fuzzy candidate reaches the list this way.
UNRANKED = 5


def _rank(wanted: str, candidate: str, brand: str) -> int:
    if candidate == wanted:
        return EXACT
    if candidate.startswith(wanted):
        return NAME_PREFIX
    if f" {wanted}" in f" {candidate}":
        return WORD_PREFIX
    if wanted in candidate:
        return SUBSTRING
    if wanted in brand:
        return BRAND
    return UNRANKED


def name_rank(query: str, name: str, brand: str | None = None) -> int:
    """The tier ``name`` falls in for ``query``; lower answers the query better."""
    wanted = normalize(query)
    if not wanted:
        return UNRANKED
    return min(
        _rank(wanted, normalize(name), normalize(brand)),
        _rank(fold(query), fold(name), fold(brand)),
    )


def matches(query: str, name: str, brand: str | None = None) -> bool:
    """Whether every word of ``query`` occurs in the name or the brand, in either spelling.

    A query without a word (empty, or nothing but punctuation) matches every row, as the
    substring search it replaces did.
    """
    spellings = (
        (normalize, f"{normalize(name)} {normalize(brand)}"),
        (fold, f"{fold(name)} {fold(brand)}"),
    )
    return all(
        any(spell(word) in text for spell, text in spellings) for word in normalize(query).split()
    )


def sort_key(query: str, name: str, brand: str | None = None) -> tuple[int, str]:
    """Sort key for one row: its tier, then its name, so a tier stays alphabetical."""
    return (name_rank(query, name, brand), normalize(name))
