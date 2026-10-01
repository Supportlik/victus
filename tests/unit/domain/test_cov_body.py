"""T-DOM-204…205: body scales at their boundaries and input that is rejected."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from victus.domain.services import body as calc

pytestmark = pytest.mark.domain


def test_a_band_is_closed_below_and_open_above() -> None:
    """T-DOM-204: a value below a class's lower edge lies outside it; the upper edge too."""
    normal = calc.Band("normal weight", 18.5, 25.0, "ok")
    assert normal.contains(18.4) is False
    assert normal.contains(18.5) is True
    assert normal.contains(25.0) is False
    top = calc.Band("open", 40.0, None, "bad")
    assert top.contains(1000.0) is True


@pytest.mark.parametrize(
    "call",
    [
        lambda: calc.bmi(0, 180),
        lambda: calc.bmi(80, -1),
        lambda: calc.waist_to_height(0, 180),
        lambda: calc.waist_to_height(90, 0),
        lambda: calc.waist_to_hip(0, 100, calc.Sex.MALE),
        lambda: calc.waist_to_hip(90, 0, calc.Sex.FEMALE),
        lambda: calc.basal_rate_kcal(80, 180, -1, calc.Sex.MALE),
        lambda: calc.basal_rate_kcal(0, 180, 30, calc.Sex.FEMALE),
        lambda: calc.split_energy(2500, 0),
    ],
)
def test_nonsense_input_raises_instead_of_returning_a_number(call: Callable[[], object]) -> None:
    """T-DOM-205: zero or negative measures raise ValueError rather than yield a figure."""
    with pytest.raises(ValueError, match="positive"):
        call()
