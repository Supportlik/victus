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
"""

from __future__ import annotations

from victus.domain.services.matching import normalize

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


def name_rank(query: str, name: str, brand: str | None = None) -> int:
    """The tier ``name`` falls in for ``query``; lower answers the query better."""
    wanted = normalize(query)
    if not wanted:
        return UNRANKED
    candidate = normalize(name)
    if candidate == wanted:
        return EXACT
    if candidate.startswith(wanted):
        return NAME_PREFIX
    if f" {wanted}" in f" {candidate}":
        return WORD_PREFIX
    if wanted in candidate:
        return SUBSTRING
    if wanted in normalize(brand or ""):
        return BRAND
    return UNRANKED


def sort_key(query: str, name: str, brand: str | None = None) -> tuple[int, str]:
    """Sort key for one row: its tier, then its name, so a tier stays alphabetical."""
    return (name_rank(query, name, brand), normalize(name))
