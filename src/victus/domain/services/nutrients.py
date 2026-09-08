"""Nutrient arithmetic — the one pure counterpart of the SQL views.

Rules (SPEC R1–R4): nutrients are never stored on a line item; they are computed
from the consumable's values per 100 base units and the item's frozen base
quantity. This module and the database views must agree to the last decimal
(``T-DOM-002``).
"""

from __future__ import annotations

from collections.abc import Iterable

from victus.domain.values import MACRO_KEYS, Macros


def macros_per_100(declared: Macros, reference_amount: float) -> Macros:
    """Normalise declared values (per ``reference_amount`` g/ml) to per 100."""
    if reference_amount <= 0:
        raise ValueError("reference_amount must be positive")
    if reference_amount == 100:
        return declared
    return declared.scaled(100.0 / reference_amount)


def line_item_macros(per_100: Macros, base_amount: float) -> Macros:
    """``value * base_amount / 100`` for every declared macro (view ``line_item_macros``)."""
    if base_amount < 0:
        raise ValueError("base_amount must not be negative")
    return per_100.scaled(base_amount / 100.0)


def batch_per_100(totals: Macros, total_weight_g: float | None) -> Macros:
    """A cooked batch's frozen totals expressed per 100 g (view ``consumable_per100``)."""
    if not total_weight_g or total_weight_g <= 0:
        return Macros()
    return totals.scaled(100.0 / total_weight_g)


def sum_macros(items: Iterable[Macros]) -> Macros:
    """Sum items; a macro stays ``None`` only when *no* item declares it."""
    total: dict[str, float | None] = dict.fromkeys(MACRO_KEYS)
    for item in items:
        for key in MACRO_KEYS:
            value = getattr(item, key)
            if value is None:
                continue
            total[key] = (total[key] or 0.0) + value
    return Macros(**total)


def day_totals(items: Iterable[Macros]) -> Macros:
    """Day totals with the display rounding of the ``day_macros`` view."""
    return sum_macros(items).rounded()
