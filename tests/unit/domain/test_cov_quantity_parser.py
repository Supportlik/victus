"""T-DOM-200…203: quantity parser edges that the diary corpus rarely produces."""

from __future__ import annotations

import pytest

from victus.domain.services.quantity_parser import (
    parse_number,
    parse_quantity,
    parse_quantity_details,
)

pytestmark = pytest.mark.domain


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("abc", None),  # no digit at all
        ("1,2,3", None),  # two decimal commas: not a number
        ("½ cup", 0.5),
        ("n/a", None),
        ("2.568", 2568.0),
    ],
)
def test_parse_number_rejects_what_is_not_a_number(text: str, expected: float | None) -> None:
    """T-DOM-200: text without a readable number yields None instead of a guess."""
    assert parse_number(text) == expected


def test_a_multiplication_without_a_unit_counts_pieces() -> None:
    """T-DOM-201: "2 x 3" counts pieces; a weight further on becomes the base amount."""
    plain = parse_quantity_details("2 x 3")
    assert plain.quantity.amount == 2
    assert plain.quantity.unit_code == "piece"
    assert plain.base_amount is None and plain.base_unit is None

    weighed = parse_quantity_details("2 x 3 (~50 g)")
    assert weighed.quantity.amount == 2
    assert weighed.quantity.unit_code == "piece"
    assert weighed.quantity.estimated is True
    assert (weighed.base_amount, weighed.base_unit) == (100.0, "g")

    # the later weight is unreadable, so there is no base amount to multiply
    unreadable = parse_quantity_details("2 x 3 then 1,2,3 g")
    assert unreadable.quantity.unit_code == "piece"
    assert unreadable.base_amount is None


def test_unreadable_numbers_fall_through_to_free_text() -> None:
    """T-DOM-202: an unreadable count or weight never produces an amount."""
    # leading weight with an unreadable number: no amount, no base
    lead = parse_quantity_details("1,2,3 g")
    assert lead.quantity.amount is None
    assert lead.quantity.unit_code is None
    assert lead.base_amount is None

    # "count × each" where the count is unreadable: no multiplication, only the one
    # readable weight in the text remains
    anywhere = parse_quantity_details("1,2,3 x 2 l")
    assert (anywhere.quantity.amount, anywhere.quantity.unit_code) == (2000.0, "ml")
    assert (anywhere.base_amount, anywhere.base_unit) == (2000.0, "ml")

    # a multiplication whose second factor is unreadable is not taken as one
    assert parse_quantity("2 x 1,2,3").unit_code is None


def test_a_weight_in_parentheses_is_not_a_portion_label() -> None:
    """T-DOM-203: "(70 g)" after a leading weight is a weight, not a label such as 'bottle'."""
    q = parse_quantity("346 g (70 g)")
    assert (q.amount, q.unit_code) == (346.0, "g")
    assert q.portion_label is None
    # whereas a count word inside the parentheses is the label
    assert parse_quantity("0,5 l (1 Flasche)").portion_label == "bottle"
