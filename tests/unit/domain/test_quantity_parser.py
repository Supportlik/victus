"""T-DOM-018 (quantity golden table) and T-DOM-019 (number normalisation)."""

from __future__ import annotations

import pytest

from victus.domain.services.quantity_parser import (
    clean_text,
    parse_number,
    parse_quantity,
    parse_quantity_details,
)

pytestmark = pytest.mark.domain


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.056", 1056.0),
        ("150,5", 150.5),
        ("2.568,25", 2568.25),
        ("12", 12.0),
        ("**1.639**", 1639.0),
        ("~80", 80.0),
        ("≈ 2,4 g", 2.4),
        ("150.5", 150.5),
        ("1.5", 1.5),
        ("-", None),
        ("–", None),
        ("", None),
        (None, None),
        ("k.A.", None),
        ("½", 0.5),
        ("<0,1", 0.1),
    ],
)
def test_parse_number(text: str | None, expected: float | None) -> None:
    """T-DOM-019."""
    assert parse_number(text) == expected


# (text, amount, unit_code, base_amount, base_unit, estimated, portion_label)
GOLDEN = [
    ("346 g", 346.0, "g", 346.0, "g", False, None),
    ("~240 g ⚠️", 240.0, "g", 240.0, "g", True, None),
    ("0,5 l (1 Flasche)", 500.0, "ml", 500.0, "ml", False, "bottle"),
    ("500 g (ganzer Becher)", 500.0, "g", 500.0, "g", False, "tub"),
    ("3 Stück", 3.0, "piece", None, None, False, "piece"),
    ("1 Stück (~70g)", 1.0, "piece", 70.0, "g", True, "piece"),
    ("½ Dose", 0.5, "can", None, None, False, "can"),
    ("2 × 300 ml", 600.0, "ml", 600.0, "ml", False, None),
    ("3 × ~250 ml", 750.0, "ml", 750.0, "ml", True, None),
    ("53 g (~2,1 Scoops)", 53.0, "g", 53.0, "g", True, "scoop"),
    ("2 Scheiben (~90 g)", 2.0, "slice", 90.0, "g", True, "slice"),
    ("1 Portion (~410 g)", 1.0, "portion", 410.0, "g", True, "portion"),
    ("380 g (ganzes Glas, abgetropft)", 380.0, "g", 380.0, "g", False, "glass"),
    ("1 Shot", 1.0, "shot", None, None, False, "shot"),
    ("3 EL (~30 g)", 3.0, "tbsp", 30.0, "g", True, "tbsp"),
    ("1 TL", 1.0, "tsp", None, None, False, "tsp"),
    ("1 Becher (400 g)", 1.0, "tub", 400.0, "g", False, "tub"),
    ("300 g (1 Pkg)", 300.0, "g", 300.0, "g", False, "pack"),
    ("0,33 l", 330.0, "ml", 330.0, "ml", False, None),
    ("1 kg", 1000.0, "g", 1000.0, "g", False, None),
    ("250ml", 250.0, "ml", 250.0, "ml", False, None),
    ("5 Hälften (~60 g)", 5.0, "piece", 60.0, "g", True, "piece"),
    ("1 Handvoll", 1.0, "handful", None, None, False, "handful"),
    ("2", 2.0, None, None, None, False, None),
    ("", None, None, None, None, False, None),
    ("ca. 100 g", 100.0, "g", 100.0, "g", True, None),
    ("1 Riegel (45 g)", 1.0, "bar", 45.0, "g", False, "bar"),
    ("1 Glas", 1.0, "glass", None, None, False, "glass"),
    ("2 kleine (~80 g)", 2.0, "piece", 80.0, "g", True, "piece"),
    ("1 Tasse (~200 ml)", 1.0, "cup", 200.0, "ml", True, "cup"),
    ("400 g (ganze Pkg)", 400.0, "g", 400.0, "g", False, "pack"),
    ("2 Sch (~90 g)", 2.0, "slice", 90.0, "g", True, "slice"),
    ("1 St (50 g)", 1.0, "piece", 50.0, "g", False, "piece"),
    ("**200 g**", 200.0, "g", 200.0, "g", False, None),
    ("2 slices (60 g)", 2.0, "slice", 60.0, "g", False, "slice"),
    ("1 cup", 1.0, "cup", None, None, False, "cup"),
]


@pytest.mark.parametrize(
    ("text", "amount", "unit", "base", "base_unit", "estimated", "label"), GOLDEN
)
def test_parse_quantity_golden(
    text: str,
    amount: float | None,
    unit: str | None,
    base: float | None,
    base_unit: str | None,
    estimated: bool,
    label: str | None,
) -> None:
    """T-DOM-018."""
    d = parse_quantity_details(text)
    q = d.quantity
    assert q.amount == pytest.approx(amount) if amount is not None else q.amount is None
    assert q.unit_code == unit
    assert d.base_amount == pytest.approx(base) if base is not None else d.base_amount is None
    assert d.base_unit == base_unit
    assert q.estimated is estimated
    assert q.portion_label == label
    assert q.raw == text


def test_parse_quantity_returns_quantity_only() -> None:
    q = parse_quantity("2 Scheiben (~90 g)")
    assert (q.amount, q.unit_code, q.estimated) == (2.0, "slice", True)


def test_clean_text_removes_wikilinks_and_decoration() -> None:
    assert clean_text("[[../../foods\\|Bergquell Skyr Natur]] 🆕") == "Bergquell Skyr Natur"
    assert clean_text("**[[Chili sin Carne]]**") == "Chili sin Carne"
    assert clean_text("[Label](https://example.com)  x") == "Label x"


@pytest.mark.parametrize(
    ("text", "base_amount", "base_unit", "amount"),
    [
        ("2 Fl. à 0,5 l", 1000.0, "ml", 2.0),
        ("2 Flaschen (2 × 0,33 l)", 660.0, "ml", 2.0),
        ("3 Scheiben à 45 g", 135.0, "g", 3.0),
        ("2 Kugeln (~160 g)", 160.0, "g", 2.0),
    ],
)
def test_multiplication_anywhere(
    text: str, base_amount: float, base_unit: str, amount: float
) -> None:
    """T-DOM-028: a count times a per-piece mass/volume yields the total base amount."""
    d = parse_quantity_details(text)
    assert d.base_amount is not None and abs(d.base_amount - base_amount) < 0.01
    assert d.base_unit == base_unit
    assert d.quantity.amount == amount
