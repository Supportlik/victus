"""Search a spoken food the way a person would, in one call (#78).

A transcript says "110 g Fitnessbrötchen from Bakery X", and the catalogue calls the same
thing "Bakery X Fitnessbrötchen (wheat 95 % / rye 5 %)". A search that needs every word of
the phrase in the name finds nothing: "110", "g" and "from" are in no name, and the bakery
may have been heard as a near-homophone. A person retries — the food's main word, the brand
alone, the word without its umlaut — and so did the drafting agent, one model turn per try.

This module does those retries itself and merges what they find:

* :func:`content_words` drops quantities, units, number words and filler words, so the
  phrase above becomes `fitnessbroetchen`, `bakery`, `x`;
* :class:`Relevance` scores a name by how much of *the query* it covers — every content
  word on its own, in both umlaut spellings (:mod:`search_ranking`), as part of a compound
  ("Fitness-Brötchen"), or as a near spelling of a word in the name ("Meier" for "Mayer") —
  and not by the length of the name, which is what used to bury long names;
* :func:`one_off_name` names a one-off after the food rather than after the sentence.

Everything here is pure: the caller hands in names, nothing is read from a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from victus.domain.services import search_ranking
from victus.domain.services.matching import fold, normalize
from victus.domain.services.quantity_parser import clean_text

# Words that say how much, of what kind of container, or nothing at all. Compared in their
# folded spelling (see ``matching.fold``), so "Stück", "Stueck" and "Stuck" are one entry.
_FILLERS = """
a an the of from with and or some about approx approximately roughly around plus also
my our his her their this that these those another other
von vom vonn der die das den dem des ein eine einen einem einer eines und oder mit aus
dazu etwa ungefaehr circa ca so noch auch plus mein meine meinen dieser diese dieses
noch nochmal again more mehr bisschen bit little etwas
"""
_NUMBER_WORDS = """
one two three four five six seven eight nine ten eleven twelve half quarter couple dozen
eins zwei drei vier fuenf sechs sieben acht neun zehn elf zwoelf halb halbe halber halbes
halben viertel paar dutzend
"""
_UNIT_WORDS = """
g gr gram grams gramm kg kilo kilos mg ml l liter litre liters litres cl dl
piece pieces pc pcs stk stueck stuecke slice slices scheibe scheiben
pack packs packet packets package packages packung packungen pkg tub tubs becher
cup cups tasse tassen glass glasses glas glaeser bottle bottles flasche flaschen can cans
dose dosen portion portions serving servings spoon spoons tbsp tsp el tl essloeffel
teeloeffel loeffel handful handvoll schale schalen schuessel teller plate plates
"""
STOP_WORDS: frozenset[str] = frozenset(
    fold(w) for w in f"{_FILLERS} {_NUMBER_WORDS} {_UNIT_WORDS}".split()
)

#: An EAN-8, UPC-A, EAN-13 or GTIN-14, the barcodes a label carries.
_EAN = re.compile(r"\d{8}|\d{12,14}")
_DIGITS_ONLY = re.compile(r"[\d\s-]+")

#: How a word that occurs only as a near spelling counts against one that occurs as typed.
SIMILAR_WEIGHT = 0.7
#: Two folded words this similar are taken as one misheard word ("meier" / "mayer" is 0.8).
SIMILAR_RATIO = 0.8
#: A near spelling is only looked for in words this long; short words are too alike.
SIMILAR_MIN_LENGTH = 4
#: A word this long is also found across a word boundary ("Fitness-Brötchen" for
#: "Fitnessbrötchen"); a shorter one would find a syllable in every second name.
COMPOUND_MIN_LENGTH = 5

#: The tier a hit falls in (see ``search_ranking``), as a share of the score.
_TIER_WEIGHT = {
    search_ranking.EXACT: 1.0,
    search_ranking.NAME_PREFIX: 0.9,
    search_ranking.WORD_PREFIX: 0.8,
    search_ranking.BRAND: 0.6,
    search_ranking.SUBSTRING: 0.5,
    search_ranking.UNRANKED: 0.0,
}
#: Coverage of the query decides most of the score; the tier orders equal coverage.
_COVERAGE_SHARE = 0.75


def _is_quantity(word: str) -> bool:
    return any(c.isdigit() for c in word)


def content_words(text: str | None) -> list[str]:
    """The words of ``text`` that name a food, in order, each once (normalised spelling).

    Quantities ("110", "110g", "6x"), units, number words and filler words are dropped.
    A text made of nothing else keeps its own words, so a search for "Glas" still looks
    for "glas".
    """
    words = normalize(text).split()
    kept: list[str] = []
    for word in words:
        if _is_quantity(word) or fold(word) in STOP_WORDS or word in kept:
            continue
        kept.append(word)
    if kept:
        return kept
    return list(dict.fromkeys(w for w in words if not _is_quantity(w) and len(w) > 1))


def variants(text: str | None) -> list[str]:
    """The queries a person would try, as a list a reader can follow.

    The text as given, the text without quantities and filler words, then each content
    word on its own — the brand alone is one of them. Scoring (:class:`Relevance`) looks at
    the same words; this list only says what was tried.
    """
    out: list[str] = []
    given = clean_text(text)
    if given:
        out.append(given)
    words = content_words(text)
    stripped = " ".join(words)
    if stripped and stripped != normalize(given):
        out.append(stripped)
    if len(words) > 1:
        out.extend(w for w in words if len(w) >= 2)
    return out


def eans_in(text: str | None) -> list[str]:
    """Barcodes in the query: the whole text when it is one (spaces and dashes allowed),
    otherwise every token that has a barcode's length."""
    raw = (text or "").strip()
    if raw and _DIGITS_ONLY.fullmatch(raw):
        digits = re.sub(r"\D", "", raw)
        return [digits] if _EAN.fullmatch(digits) else []
    return [t for t in re.findall(r"\d+", raw) if _EAN.fullmatch(t)]


@dataclass(frozen=True, slots=True)
class Hit:
    """How well one name answers the query."""

    #: 0–1: how much of the query the name covers, then how well the best word sits in it.
    score: float
    #: The best ``search_ranking`` tier among the words found as typed.
    tier: int
    #: The query words found in the name or brand, as typed or as a near spelling.
    matched: tuple[str, ...]


@dataclass(slots=True)
class Relevance:
    """Scores names against one query; build once per search, call per row.

    Near spellings are compared word against word and remembered, because a catalogue
    repeats its brands and nouns across many rows.
    """

    query: str
    words: list[str] = field(init=False)
    _folded: list[str] = field(init=False)
    _similar: dict[tuple[str, str], bool] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.words = content_words(self.query)
        self._folded = [fold(w) for w in self.words]

    def _near(self, word: str, tokens: list[str]) -> bool:
        if len(word) < SIMILAR_MIN_LENGTH:
            return False
        for token in tokens:
            if len(token) < SIMILAR_MIN_LENGTH:
                continue
            key = (word, token)
            known = self._similar.get(key)
            if known is None:
                matcher = SequenceMatcher(None, word, token)
                known = (
                    matcher.real_quick_ratio() >= SIMILAR_RATIO
                    and matcher.quick_ratio() >= SIMILAR_RATIO
                    and matcher.ratio() >= SIMILAR_RATIO
                )
                self._similar[key] = known
            if known:
                return True
        return False

    def of(self, name: str, brand: str | None = None) -> Hit | None:
        """The hit for one row, or ``None`` when no word of the query is in it."""
        if not self.words:
            return None
        folded = f"{fold(name)} {fold(brand)}".strip()
        compact = folded.replace(" ", "")
        tokens = folded.split()
        found = 0.0
        matched: list[str] = []
        tiers: list[int] = []
        for word, folded_word in zip(self.words, self._folded, strict=True):
            compound = len(folded_word) >= COMPOUND_MIN_LENGTH and folded_word in compact
            if compound or search_ranking.matches(word, name, brand):
                found += 1.0
                matched.append(word)
                tiers.append(search_ranking.name_rank(word, name, brand))
            elif self._near(folded_word, tokens):
                found += SIMILAR_WEIGHT
                matched.append(word)
        if not matched:
            return None
        if len(matched) == len(self.words) and len(self.words) > 1:
            tiers.append(search_ranking.name_rank(" ".join(self.words), name, brand))
        tier = min(tiers, default=search_ranking.UNRANKED)
        coverage = found / len(self.words)
        score = _COVERAGE_SHARE * coverage + (1 - _COVERAGE_SHARE) * _TIER_WEIGHT[tier]
        return Hit(score=round(score, 3), tier=tier, matched=tuple(matched))


def one_off_name(raw_text: str | None) -> str:
    """A name for a one-off: the food, without the amount and the words around it.

    "110 g Fitnessbrötchen from Bakery X" becomes "Fitnessbrötchen from Bakery X":
    quantities and the unit that follows them go wherever they are, and number words,
    units and filler words go from both ends. The words in the middle stay as they were
    written — "Salt and Pepper Crisps" keeps its "and". A text with nothing left keeps
    its own wording.
    """
    words = clean_text(raw_text).split()
    kept: list[str] = []
    skip_unit = False
    for word in words:
        if _is_quantity(word):
            skip_unit = True
            continue
        bare = fold(word)
        if skip_unit and bare in STOP_WORDS:
            continue
        skip_unit = False
        kept.append(word)

    def stop(word: str) -> bool:
        bare = fold(word)
        return not bare or bare in STOP_WORDS

    while kept and stop(kept[0]):
        kept.pop(0)
    while kept and stop(kept[-1]):
        kept.pop()
    name = " ".join(kept).strip(" ,;:-")
    if not any(len(fold(word)) > 1 for word in kept):
        name = clean_text(raw_text)
    return name[:1].upper() + name[1:]


def same_food(a: str | None, b: str | None) -> bool:
    """Whether two one-off names are one food: equal once folded (case, umlauts, signs)."""
    left = fold(a)
    return bool(left) and left == fold(b)
