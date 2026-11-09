"""The Open Food Facts adapter against a faked ``urlopen`` (no network). T-AGT-126, T-AGT-127."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from victus.application.ports.product_lookup import ProductLookupError
from victus.infrastructure.lookup import openfoodfacts as mod
from victus.infrastructure.lookup.openfoodfacts import OpenFoodFactsLookup, parse_product

pytestmark = pytest.mark.domain

URL = "https://off.victus.example.com/api/v2/product/{ean}.json"
EAN = "4000000000017"
BODY: dict[str, Any] = {
    "status": 1,
    "code": EAN,
    "product": {
        "product_name": "Pasta bake ",
        "brands": "Brand W, Brand W Group",
        "quantity": "400 g",
        "product_quantity": "400",
        "product_quantity_unit": "g",
        "serving_size": "200 g",
        "nutriments": {
            "energy-kcal_100g": 142,
            "proteins_100g": 6.1,
            "carbohydrates_100g": "17",
            "fat_100g": 5.2,
            "fiber_100g": "",
            "salt_100g": 0.9,
        },
    },
}


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _adapter(monkeypatch: pytest.MonkeyPatch, answer: Any) -> tuple[OpenFoodFactsLookup, list]:
    seen: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        seen.append(request)
        assert timeout == 2.5
        if isinstance(answer, Exception):
            raise answer
        return _Response(answer if isinstance(answer, bytes) else json.dumps(answer).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    return OpenFoodFactsLookup(URL, timeout_s=2.5, user_agent="Victus/test"), seen


def test_t_agt_126_a_known_barcode_is_mapped_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-AGT-126: one request with only the barcode in the URL and a user agent; name, first
    brand, values per 100 g and the pack size come back; a second lookup is served from cache."""
    adapter, seen = _adapter(monkeypatch, BODY)
    found = adapter.by_ean(EAN)
    assert found is not None
    assert found.name == "Pasta bake" and found.brand == "Brand W"
    assert (found.kcal, found.protein, found.carbs, found.fat) == (142.0, 6.1, 17.0, 5.2)
    assert found.fiber is None and found.salt == 0.9
    assert found.pack_amount == 400.0 and found.reference_unit == "g"
    assert found.source_url.endswith(f"/product/{EAN}")
    assert adapter.by_ean(EAN) is found
    assert len(seen) == 1
    assert seen[0].full_url.startswith(URL.format(ean=EAN) + "?fields=")
    assert seen[0].get_header("User-agent") == "Victus/test"


def test_t_agt_127_unknown_failing_and_odd_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-AGT-127: status 0 and HTTP 404 mean "unknown" (None); other HTTP errors, an
    unreachable host and an unreadable body raise ProductLookupError; kJ-only energy is
    converted and a liquid's unit becomes ml."""
    adapter, _ = _adapter(monkeypatch, {"status": 0})
    assert adapter.by_ean(EAN) is None
    not_found = urllib.error.HTTPError(URL, 404, "Not Found", {}, None)  # type: ignore[arg-type]
    adapter, _ = _adapter(monkeypatch, not_found)
    assert adapter.by_ean(EAN) is None
    for failure in (
        urllib.error.HTTPError(URL, 503, "Busy", {}, None),  # type: ignore[arg-type]
        urllib.error.URLError("no route"),
        TimeoutError("slow"),
        b"<html>not json</html>",
    ):
        adapter, _ = _adapter(monkeypatch, failure)
        with pytest.raises(ProductLookupError):
            adapter.by_ean(EAN)

    drink = parse_product(
        EAN,
        {
            "status": 1,
            "product": {"product_quantity_unit": "l", "nutriments": {"energy_100g": 418.4}},
        },
    )
    assert drink is not None
    assert drink.reference_unit == "ml" and drink.kcal == 100.0
    assert drink.name is None and drink.brand is None and drink.quantity is None
    assert parse_product(EAN, {"status": 1, "product": "x"}) is None
    assert parse_product(EAN, {"status": 1, "product": {"nutriments": []}}) is not None
    assert parse_product(EAN, ["not", "a", "dict"]) is None
