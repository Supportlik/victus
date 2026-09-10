"""T-DOM-086: grams and millilitres are only interchangeable through a density."""

from __future__ import annotations

import pytest

from victus.domain.services.units import convert_base

pytestmark = pytest.mark.domain


def test_convert_base_uses_the_density_in_both_directions() -> None:
    assert convert_base(100, "ml", "g", 1.32) == pytest.approx(132.0)
    assert convert_base(132, "g", "ml", 1.32) == pytest.approx(100.0)
    assert convert_base(10, "ml", "g", 0.92) == pytest.approx(9.2)


def test_same_unit_is_left_alone_even_without_a_density() -> None:
    assert convert_base(250, "g", "g", None) == 250
    assert convert_base(250, "ml", "ml", None) == 250


def test_without_a_usable_density_there_is_no_answer() -> None:
    """``None`` rather than the amount itself: the caller has to decide what to do."""
    assert convert_base(100, "ml", "g", None) is None
    assert convert_base(100, "ml", "g", 0) is None
    assert convert_base(100, "g", "ml", -1.0) is None


def test_a_unit_that_is_neither_g_nor_ml_is_not_converted() -> None:
    assert convert_base(2, "tbsp", "g", 1.32) is None
