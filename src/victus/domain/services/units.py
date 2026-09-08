"""Unit master data.

One list serves three consumers: the quantity parser (recognition patterns),
the database seed (``unit`` table) and the API (display names). Codes are
English; the recognition patterns accept German and English spellings because
the vault importer reads German source text.

Mass and volume units convert to a base unit (g / ml) through ``factor_base``.
Count units (``needs_portion``) cannot be converted without a portion weight;
``fuzzy`` marks units whose size is inherently vague (handful, dash).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from victus.domain.values import UnitType


@dataclass(frozen=True, slots=True)
class UnitSpec:
    code: str
    unit_type: UnitType
    singular: str
    plural: str
    factor_base: float | None  # only mass/volume: to g resp. ml
    needs_portion: bool
    fuzzy: bool
    synonyms: tuple[str, ...]  # regex fragments, matched case-insensitively


def _u(
    code: str,
    unit_type: UnitType,
    singular: str,
    plural: str,
    factor: float | None,
    *synonyms: str,
    fuzzy: bool = False,
) -> UnitSpec:
    return UnitSpec(
        code=code,
        unit_type=unit_type,
        singular=singular,
        plural=plural,
        factor_base=factor,
        needs_portion=unit_type is UnitType.COUNT,
        fuzzy=fuzzy,
        synonyms=synonyms,
    )


M, V, C = UnitType.MASS, UnitType.VOLUME, UnitType.COUNT

UNITS: dict[str, UnitSpec] = {
    u.code: u
    for u in (
        _u("g", M, "g", "g", 1.0, r"g", r"gramm?", r"grams?"),
        _u("kg", M, "kg", "kg", 1000.0, r"kg", r"kilo(?:gramm?|grams?)?"),
        _u("ml", V, "ml", "ml", 1.0, r"ml", r"millilit(?:er|re)s?"),
        _u("l", V, "l", "l", 1000.0, r"l", r"lit(?:er|re)s?"),
        _u(
            "piece",
            C,
            "piece",
            "pieces",
            None,
            r"st(?:ü|ue)ck",
            r"stk",
            r"st",
            r"pieces?",
            r"pcs?",
            r"h(?:ä|ae)lften?",
            r"halves",
            r"half",
            r"kleine",
            r"gro(?:ß|ss)e",
        ),
        _u("slice", C, "slice", "slices", None, r"scheiben?", r"sch", r"slices?"),
        _u(
            "portion",
            C,
            "portion",
            "portions",
            None,
            r"portionen?",
            r"portionspack",
            r"portions?",
            r"servings?",
        ),
        _u("tub", C, "tub", "tubs", None, r"becher", r"tubs?", r"pots?"),
        _u("ball", C, "ball", "balls", None, r"kugeln?", r"balls?"),
        _u("pouch", C, "pouch", "pouches", None, r"beutel", r"pouch(?:es)?", r"sachets?"),
        _u("pack", C, "pack", "packs", None, r"packungen?", r"pkg", r"packs?", r"packages?"),
        _u("bag", C, "bag", "bags", None, r"t(?:ü|ue)ten?", r"bags?"),
        _u("glass", C, "glass", "glasses", None, r"gl(?:ä|ae)ser", r"glas", r"glass(?:es)?"),
        _u("can", C, "can", "cans", None, r"dosen?", r"cans?", r"tins?"),
        _u("bowl", C, "bowl", "bowls", None, r"schalen?", r"bowls?", r"trays?"),
        _u("bottle", C, "bottle", "bottles", None, r"flaschen?", r"bottles?"),
        _u("strip", C, "strip", "strips", None, r"streifen", r"strips?"),
        _u("cup", C, "cup", "cups", None, r"tassen?", r"cups?", r"mugs?"),
        _u("tbsp", C, "tbsp", "tbsp", None, r"el", r"essl(?:ö|oe)ffel", r"tbsp", r"tablespoons?"),
        _u("tsp", C, "tsp", "tsp", None, r"tl", r"teel(?:ö|oe)ffel", r"tsp", r"teaspoons?"),
        _u("cube", C, "cube", "cubes", None, r"w(?:ü|ue)rfel", r"cubes?"),
        _u("scoop", C, "scoop", "scoops", None, r"scoops?", r"messl(?:ö|oe)ffel"),
        _u("leaf", C, "leaf", "leaves", None, r"bl(?:ä|ae)tter", r"blatt", r"lea(?:f|ves)"),
        _u("clove", C, "clove", "cloves", None, r"zehen?", r"cloves?"),
        _u("shot", C, "shot", "shots", None, r"shots?"),
        _u("bar", C, "bar", "bars", None, r"riegel", r"bars?"),
        _u(
            "dash",
            C,
            "dash",
            "dashes",
            None,
            r"schuss",
            r"spritzer",
            r"dash(?:es)?",
            r"splash(?:es)?",
            fuzzy=True,
        ),
        _u("handful", C, "handful", "handfuls", None, r"handvoll", r"handfuls?", fuzzy=True),
        _u("pinch", C, "pinch", "pinches", None, r"prisen?", r"pinch(?:es)?", fuzzy=True),
    )
}

# Order matters for recognition: specific words before short abbreviations, and
# the two-letter German abbreviations (EL/TL/St/Sch) only as whole words.
COUNT_CODES: tuple[str, ...] = tuple(
    u.code for u in UNITS.values() if u.unit_type is UnitType.COUNT
)
BASE_CODES: tuple[str, ...] = tuple(
    u.code for u in UNITS.values() if u.unit_type is not UnitType.COUNT
)


def _pattern(spec: UnitSpec) -> re.Pattern[str]:
    alts = "|".join(spec.synonyms)
    return re.compile(rf"(?<![a-zäöüß])(?:{alts})(?![a-zäöüß])", re.IGNORECASE)


COUNT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (code, _pattern(UNITS[code])) for code in COUNT_CODES
)

BASE_UNIT_RE = re.compile(r"(\d[\d.,]*)\s*(kg|g|ml|l)(?![a-zäöüß])", re.IGNORECASE)


def base_factor(code: str) -> tuple[float, str] | None:
    """``kg`` → (1000, 'g'); ``l`` → (1000, 'ml'); ``g``/``ml`` → (1, itself)."""
    spec = UNITS.get(code)
    if spec is None or spec.factor_base is None:
        return None
    base = "g" if spec.unit_type is UnitType.MASS else "ml"
    return spec.factor_base, base
