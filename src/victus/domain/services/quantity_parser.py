"""Parse human-written quantities such as ``1 Stück (~70 g)`` or ``0,5 l (1 Flasche)``.

Pure functions. The rules were derived from ~2,800 diary rows of the source
vault; the hard-won ones are documented inline. German *and* English spellings
are recognised (the importer reads German source text), output codes are the
English unit codes from ``units.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from victus.domain.services.units import (
    BASE_UNIT_RE,
    COUNT_PATTERNS,
    UNITS,
    base_factor,
)
from victus.domain.values import Quantity

FRACTIONS: dict[str, float] = {
    "½": 0.5,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "¼": 0.25,
    "¾": 0.75,
    "⅛": 0.125,
}

_ESTIMATE_MARKERS = re.compile(r"~|≈|\bca\.?\b|\betwa\b|\bapprox\.?\b|\bcirca\b|⚠️", re.IGNORECASE)
_DECORATION = re.compile(r"\*\*|`|⚠️|🆕|✓|✅")
_NUMBER = re.compile(r"\d[\d.,]*")
_MULTIPLY = re.compile(
    r"(\d[\d.,]*|[½⅓⅔¼¾⅛])\s*[x×]\s*~?\s*(\d[\d.,]*)\s*(kg|g|ml|l)?(?![a-zäöüß])", re.I
)
_LEADING_NUMBER = re.compile(r"^\s*(\d[\d.,]*|[½⅓⅔¼¾⅛])")
# "2 Fl. à 0,5 l", "2 Flaschen (2 × 0,33 l)": a count times a per-piece mass/volume anywhere.
_MULT_ANYWHERE = re.compile(
    r"(\d[\d.,]*|[½⅓⅔¼¾⅛])\s*(?:[x×*]|(?:[A-Za-zäöüß.]+\s+)?à)\s*~?\s*(\d[\d.,]*)\s*(kg|g|ml|l)(?![a-zäöüß])",
    re.IGNORECASE,
)
_LEADING_BASE = re.compile(r"^\s*~?\s*(\d[\d.,]*)\s*(kg|g|ml|l)(?![a-zäöüß])", re.IGNORECASE)
_PARENS = re.compile(r"\(([^)]*)\)")
# Wikilinks and Markdown links. Each negated class excludes the *opening* bracket as well as
# the closing one, so a failed attempt stops at the next bracket instead of walking to the
# end of the text: without that, a pasted "[[[[[[…" costs one full scan per position, and
# this text comes from a person or a transcript. A label or URL containing "[" or "(" is not
# a link either way. The "\?" that used to precede the pipe was dead — the class before it
# already swallows the backslash of an escaped "\|" — and only added backtracking.
_WIKILINK_LABELLED = re.compile(r"\[\[[^\][|]*\|([^\][]+)\]\]")
_WIKILINK = re.compile(r"\[\[([^\][]+)\]\]")
_MD_LINK = re.compile(r"\[([^\][]+)\]\([^()]*\)")
_WHITESPACE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """Strip Markdown decoration and wikilinks, collapse whitespace."""
    if not text:
        return ""
    s = _WIKILINK_LABELLED.sub(r"\1", text)  # [[target\|Label]] → Label
    s = _WIKILINK.sub(r"\1", s)
    s = _MD_LINK.sub(r"\1", s)  # [Label](url) → Label
    s = _DECORATION.sub("", s)
    return _WHITESPACE.sub(" ", s).strip()


def parse_number(text: str | None) -> float | None:
    """``'1.234'`` → 1234 · ``'150,5'`` → 150.5 · ``'~80'`` → 80 · ``'-'`` → None.

    German notation (comma decimal, dot thousands) and English notation are
    both accepted; a lone dot followed by exactly three digits is a thousands
    separator (``2.568`` → 2568), anything else is a decimal point.
    """
    if text is None:
        return None
    s = _DECORATION.sub("", str(text))
    s = s.replace("~", "").replace("≈", "").strip()
    if not s or s in {"-", "–", "—", "?", "k.A.", "n/a", "n.a."}:
        return None
    for frac, value in FRACTIONS.items():
        if s.startswith(frac):
            return value
    m = _NUMBER.search(s)
    if not m:
        return None
    t = m.group(0).rstrip(".,")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif (t.count(".") == 1 and len(t.split(".")[1]) == 3) or t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class QuantityDetails:
    """``parse_quantity_details`` result: the captured quantity plus the base amount.

    ``base_amount``/``base_unit`` is the mass or volume that can actually be
    multiplied with nutrients per 100 g/ml — taken from the text when present
    (``1 piece (~70 g)`` → 70 g), otherwise ``None`` (count unit without weight).
    """

    quantity: Quantity
    base_amount: float | None
    base_unit: str | None  # 'g' | 'ml'


def _to_base(amount: float, code: str) -> tuple[float, str]:
    factor = base_factor(code)
    assert factor is not None
    return amount * factor[0], factor[1]


def _count_unit_in(text: str) -> str | None:
    for code, pattern in COUNT_PATTERNS:
        if pattern.search(text):
            return code
    return None


def parse_quantity_details(text: str | None) -> QuantityDetails:
    """Full parse; see module docstring for the recognised shapes."""
    raw = (text or "").strip()
    cleaned = clean_text(raw)
    estimated = bool(_ESTIMATE_MARKERS.search(raw))
    if not cleaned:
        return QuantityDetails(Quantity(None, None, raw, estimated, None), None, None)

    low = cleaned.lower()

    # "2 × 300 ml" / "3 × ~250 ml" / "2 × 40 g": multiply into the base amount.
    mult = _MULTIPLY.match(cleaned)
    if mult:
        count = parse_number(mult.group(1))
        each = parse_number(mult.group(2))
        unit = (mult.group(3) or "").lower()
        if count is not None and each is not None and unit:
            total, total_unit = _to_base(count * each, unit)
            label = _paren_label(cleaned)
            return QuantityDetails(
                Quantity(total, total_unit, raw, estimated, label), total, total_unit
            )
        if count is not None and each is not None:
            # "2×" without unit but a weight further on ("2× (~50 g)")
            base_hit = BASE_UNIT_RE.search(low)
            if base_hit:
                each_amt = parse_number(base_hit.group(1))
                if each_amt is not None:
                    total, total_unit = _to_base(count * each_amt, base_hit.group(2).lower())
                    return QuantityDetails(
                        Quantity(count, "piece", raw, estimated, None), total, total_unit
                    )
            return QuantityDetails(Quantity(count, "piece", raw, estimated, None), None, None)

    # Leading mass/volume: "346 g", "0,5 l (1 Flasche)", "500 g (ganzer Becher)", "~240 g".
    lead = _LEADING_BASE.match(cleaned)
    if lead:
        amount = parse_number(lead.group(1))
        unit = lead.group(2).lower()
        if amount is not None:
            total, total_unit = _to_base(amount, unit)
            label = _paren_label(cleaned)
            return QuantityDetails(
                Quantity(total, total_unit, raw, estimated, label), total, total_unit
            )

    # A multiplication somewhere in the text: "2 Fl. à 0,5 l", "2 Flaschen (2 × 0,33 l)".
    anywhere = _MULT_ANYWHERE.search(cleaned)
    if anywhere:
        count = parse_number(anywhere.group(1))
        each = parse_number(anywhere.group(2))
        if count is not None and each is not None:
            total, total_unit = _to_base(count * each, anywhere.group(3).lower())
            mult_code = _count_unit_in(low) or "piece"
            mult_lead = _LEADING_NUMBER.match(cleaned)
            mult_amount = parse_number(mult_lead.group(1)) if mult_lead else count
            return QuantityDetails(
                Quantity(mult_amount, mult_code, raw, estimated, UNITS[mult_code].singular),
                total,
                total_unit,
            )

    # Count unit anywhere (before any weight): "1 Stück (~70 g)", "½ Dose", "3 Scheiben".
    code = _count_unit_in(low)
    lead_num = _LEADING_NUMBER.match(cleaned)
    amount = parse_number(lead_num.group(1)) if lead_num else None
    base_hit = BASE_UNIT_RE.search(low)
    base: float | None = None
    base_unit: str | None = None
    if base_hit:
        each = parse_number(base_hit.group(1))
        if each is not None:
            base, base_unit = _to_base(each, base_hit.group(2).lower())
    if code is not None:
        count = amount if amount is not None else 1.0
        return QuantityDetails(
            Quantity(count, code, raw, estimated, UNITS[code].singular), base, base_unit
        )

    # A weight somewhere in the text but no leading number ("ganze Packung 300 g").
    if base is not None:
        return QuantityDetails(Quantity(base, base_unit, raw, estimated, None), base, base_unit)

    # Bare number ("2") or free text ("etwas").
    return QuantityDetails(Quantity(amount, None, raw, estimated, None), None, None)


def parse_quantity(text: str | None) -> Quantity:
    """``Quantity`` only; use ``parse_quantity_details`` when the base amount is needed."""
    return parse_quantity_details(text).quantity


def _paren_label(cleaned: str) -> str | None:
    """``0,5 l (1 Flasche)`` → 'bottle'; ``500 g (ganzer Becher)`` → 'tub'; else None."""
    m = _PARENS.search(cleaned)
    if not m:
        return None
    inner = m.group(1).lower()
    if BASE_UNIT_RE.search(inner) and _count_unit_in(inner) is None:
        return None  # "(~70 g)" is a weight, not a label
    code = _count_unit_in(inner)
    return UNITS[code].singular if code else None
