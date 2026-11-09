"""Open Food Facts by barcode (``agent.lookup.ean``).

One GET per lookup against ``agent.lookup.ean_url`` with a short timeout. Only the barcode
leaves the server. Answers are cached for the life of the adapter, so a run that sees the
same pack twice asks once.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from victus.application.ports.product_lookup import LookedUpProduct, ProductLookupError

FIELDS = (
    "code,product_name,brands,quantity,product_quantity,product_quantity_unit,"
    "serving_size,nutriments"
)
PRODUCT_PAGE = "https://world.openfoodfacts.org/product/{ean}"


class OpenFoodFactsLookup:
    def __init__(self, url_template: str, *, timeout_s: float = 5.0, user_agent: str) -> None:
        self._url = url_template
        self._timeout = timeout_s
        self._user_agent = user_agent
        self._cache: dict[str, LookedUpProduct | None] = {}

    def by_ean(self, ean: str) -> LookedUpProduct | None:
        if ean in self._cache:
            return self._cache[ean]
        url = self._url.format(ean=ean) + f"?fields={FIELDS}"
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self._cache[ean] = None
                return None
            raise ProductLookupError(f"Open Food Facts answered {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProductLookupError(f"Open Food Facts not reachable: {exc}") from exc
        except ValueError as exc:
            raise ProductLookupError("Open Food Facts sent an unreadable answer") from exc
        found = parse_product(ean, body)
        self._cache[ean] = found
        return found


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_product(ean: str, body: Any) -> LookedUpProduct | None:
    """Map an Open Food Facts v2 answer; ``None`` when it says the barcode is unknown."""
    if not isinstance(body, dict) or body.get("status") != 1:
        return None
    product = body.get("product")
    if not isinstance(product, dict):
        return None
    n = product.get("nutriments")
    if not isinstance(n, dict):
        n = {}
    unit = str(product.get("product_quantity_unit") or "g").lower()
    reference_unit = "ml" if unit in ("ml", "l", "cl") else "g"
    kcal = _number(n.get("energy-kcal_100g"))
    if kcal is None and _number(n.get("energy_100g")) is not None:
        kcal = round(float(n["energy_100g"]) / 4.184, 1)  # kJ → kcal
    return LookedUpProduct(
        ean=ean,
        name=(str(product["product_name"]).strip() or None)
        if product.get("product_name")
        else None,
        brand=(str(product["brands"]).split(",")[0].strip() or None)
        if product.get("brands")
        else None,
        reference_unit=reference_unit,
        kcal=kcal,
        protein=_number(n.get("proteins_100g")),
        carbs=_number(n.get("carbohydrates_100g")),
        fat=_number(n.get("fat_100g")),
        fiber=_number(n.get("fiber_100g")),
        salt=_number(n.get("salt_100g")),
        quantity=str(product["quantity"]) if product.get("quantity") else None,
        pack_amount=_number(product.get("product_quantity")),
        serving_size=str(product["serving_size"]) if product.get("serving_size") else None,
        source=f"Open Food Facts, EAN {ean}",
        source_url=PRODUCT_PAGE.format(ean=ean),
    )
