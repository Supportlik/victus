"""Product lookup port: a barcode in, label values out (#78).

The first adapter queries Open Food Facts
(``infrastructure/lookup/openfoodfacts.py``); tests use a fake. Only the barcode leaves
the server. Adapters never see the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LookedUpProduct:
    """What a public database says about one barcode. Values are per 100 g or 100 ml."""

    ean: str
    name: str | None
    brand: str | None
    reference_unit: str  # "g" | "ml"
    kcal: float | None
    protein: float | None
    carbs: float | None
    fat: float | None
    fiber: float | None
    salt: float | None
    #: The pack size as printed ("400 g") and as a number in ``reference_unit``.
    quantity: str | None
    pack_amount: float | None
    serving_size: str | None
    source: str
    source_url: str


class ProductLookupError(Exception):
    """The lookup service failed (network, timeout, an answer that cannot be read)."""


class ProductLookupPort(Protocol):
    def by_ean(self, ean: str) -> LookedUpProduct | None:
        """The product for ``ean``, or ``None`` when the database does not know it."""
        ...
