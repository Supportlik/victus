"""T-SVC-409…416, 452: product, version, portion and category use cases at their edges."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import products as uc
from victus.application.use_cases import recipes as recipe_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db import orm

pytestmark = pytest.mark.service

DAY = date(2026, 3, 10)


def _v(pid: int, start: date | None, end: date | None) -> Any:
    return SimpleNamespace(id=pid, valid_from=start, valid_until=end)


def test_t_svc_409_valid_on_picks_the_version_of_a_day() -> None:
    """T-SVC-409: no versions → none; a day outside every version → none; without a day the
    open-ended one wins, and with none open the one that ended last."""
    assert uc.valid_on([], DAY) is None
    closed = [
        _v(1, date(2026, 1, 1), date(2026, 1, 31)),
        _v(2, date(2026, 2, 1), date(2026, 2, 28)),
    ]
    assert uc.valid_on(closed, DAY) is None
    assert uc.valid_on(closed, None).id == 2  # type: ignore[union-attr]
    assert uc.valid_on([*closed, _v(3, date(2026, 3, 1), None)], None).id == 3  # type: ignore[union-attr]


def _product(factory: UowFactory, ctx: TenantContext, name: str, **kw: Any) -> int:
    data = {"kcal": 100, "protein": 1, "carbs": 1, "fat": 1, "fiber": 1, "salt": 0, **kw}
    return uc.CreateProduct(factory, ctx).execute(uc.ProductInput(name=name, **data)).id


def test_t_svc_410_create_validation_and_category_lookup(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-410: a blank name, a foreign reference unit, a zero amount and a twin are
    refused; a category id is used as given; a category name is found or created once."""
    for bad, match in (
        (uc.ProductInput(name="  "), "name is required"),
        (uc.ProductInput(name="Oats", reference_unit="oz"), "reference_unit"),
        (uc.ProductInput(name="Oats", reference_amount=0), "reference_amount"),
    ):
        with pytest.raises(ValidationFailed, match=match):
            uc.CreateProduct(factory, alice).execute(bad)
    cereals = uc.CreateCategory(factory, alice).execute("Cereals")
    with pytest.raises(Conflict):
        uc.CreateCategory(factory, alice).execute("Cereals")
    oats = uc.CreateProduct(factory, alice).execute(
        uc.ProductInput(name="Oats", category_id=cereals.id, kcal=370)
    )
    assert oats.category_id == cereals.id
    with pytest.raises(Conflict, match="already exists"):
        uc.CreateProduct(factory, alice).execute(uc.ProductInput(name="Oats"))
    rye = uc.CreateProduct(factory, alice).execute(uc.ProductInput(name="Rye", category="Cereals"))
    assert rye.category_id == cereals.id


def test_t_svc_411_search_by_category_and_version_on_a_day(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-411: a query narrowed to a category keeps only its products, fuzzy hits
    included; a day before every version of a product finds none of it; unknown ids in
    ``ProductVersions`` are 404."""
    dairy = uc.CreateCategory(factory, alice).execute("Dairy")
    _product(factory, alice, "Skyr natural", category_id=dairy.id)
    _product(factory, alice, "Skyr bar")  # no category
    found = uc.SearchProducts(factory, alice).execute("skyr", category_id=dairy.id)
    assert [p.name for p in found] == ["Skyr natural"]
    # SQL folds the query to ASCII and misses the accented name; the fuzzy matcher finds it,
    # and the category filter applies to its hits as well
    _product(factory, alice, "Crème fraîche", category_id=dairy.id)
    fuzzy = uc.SearchProducts(factory, alice).execute("creme fraiche", category_id=dairy.id)
    assert [p.name for p in fuzzy] == ["Crème fraîche"]
    other = uc.CreateCategory(factory, alice).execute("Bakery")
    assert uc.SearchProducts(factory, alice).execute("creme fraiche", category_id=other.id) == []

    tea = _product(factory, alice, "Green tea")
    uc.NewProductVersion(factory, alice).execute(tea, date(2026, 3, 1), {"kcal": 2})
    with factory(alice) as uow:  # the first version starts on a day as well
        first = uow.products.get(tea)
        assert first is not None
        first.valid_from = date(2026, 2, 1)
        uow.commit()
    before = uc.SearchProducts(factory, alice).execute("", on=date(2026, 1, 1))
    assert "Green tea" not in [p.name for p in before]
    with pytest.raises(NotFound):
        uc.ProductVersions(factory, alice).execute(999_999)


def test_t_svc_412_new_version_renames_recategorises_and_keeps_an_earlier_end(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-SVC-412: a version may carry a new name and a category by name; an unknown product
    is 404; a predecessor that already ends before the new start keeps its own end."""
    with pytest.raises(NotFound):
        uc.NewProductVersion(factory, alice).execute(999_999, DAY)
    bar = _product(factory, alice, "Protein bar")
    early_end = DAY - timedelta(days=10)
    with session_factory() as s:
        row = s.get(orm.Product, bar)
        assert row is not None
        row.valid_until = early_end
        s.commit()
    fresh = uc.NewProductVersion(factory, alice).execute(
        bar, DAY, {"name": "Protein bar (new recipe)", "category": "Snacks", "kcal": 350}
    )
    assert fresh.name == "Protein bar (new recipe)" and fresh.kcal == 350
    assert fresh.category_id is not None
    old = uc.GetProduct(factory, alice).execute(bar)
    assert old.valid_until == early_end
    blank = uc.NewProductVersion(factory, alice).execute(
        fresh.id, DAY + timedelta(days=5), {"name": " "}
    )
    assert blank.name == "Protein bar (new recipe)"


def test_t_svc_413_update_rename_category_and_reference_guard(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-413: a rename to a free name is applied, to a taken one is 409; a category by
    name is resolved; an invalid reference unit is refused."""
    milk = _product(factory, alice, "Milk")
    _product(factory, alice, "Oat drink")
    renamed = uc.UpdateProduct(factory, alice).execute(milk, {"name": " Whole milk "})
    assert renamed.name == "Whole milk"
    same = uc.UpdateProduct(factory, alice).execute(milk, {"name": "Whole milk"})
    assert same.name == "Whole milk"
    with pytest.raises(Conflict):
        uc.UpdateProduct(factory, alice).execute(milk, {"name": "Oat drink"})
    moved = uc.UpdateProduct(factory, alice).execute(milk, {"category": "Dairy"})
    assert moved.category_id is not None
    with pytest.raises(ValidationFailed, match="reference"):
        uc.UpdateProduct(factory, alice).execute(milk, {"reference_unit": "oz"})


def test_t_svc_414_referenced_product_and_portion_cannot_be_deleted(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-414: a product logged in a day and a portion a line item uses are kept (409)."""
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = day_uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    portion = uc.GetProduct(factory, alice).execute(skyr).portions[0]
    day_uc.AddLineItem(factory, alice).execute(
        meal.id,
        day_uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="tub", portion_id=portion.id),
    )
    with pytest.raises(Conflict, match="referenced"):
        uc.DeleteProduct(factory, alice).execute(skyr)
    with pytest.raises(Conflict, match="referenced"):
        uc.DeletePortion(factory, alice).execute(portion.id)


def test_t_svc_415_portion_guards_and_default_switching(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-415: an unknown unit, a non-positive amount, a foreign amount unit and an unknown
    product are refused; a new default replaces the old one of the same unit, and an update
    can make a portion the default or take that away."""
    with pytest.raises(ValidationFailed, match="unknown unit"):
        uc.AddPortion(factory, alice).execute(skyr, uc.PortionInput("bucket", "bucket", 5))
    with pytest.raises(ValidationFailed, match="positive"):
        uc.AddPortion(factory, alice).execute(skyr, uc.PortionInput("tub", "tub", 0))
    with pytest.raises(ValidationFailed, match="positive"):
        uc.AddPortion(factory, alice).execute(
            skyr, uc.PortionInput("tub", "tub", 5, amount_unit="oz")
        )
    with pytest.raises(NotFound):
        uc.AddPortion(factory, alice).execute(999_999, uc.PortionInput("tub", "tub", 5))

    big = uc.AddPortion(factory, alice).execute(
        skyr, uc.PortionInput("tub", "big tub", 500, is_default=True)
    )
    portions = {p.id: p for p in uc.GetProduct(factory, alice).execute(skyr).portions}
    assert portions[big.id].is_default and sum(p.is_default for p in portions.values()) == 1
    small = next(pid for pid in portions if pid != big.id)

    uc.UpdatePortion(factory, alice).execute(small, {"is_default": True})
    portions = {p.id: p for p in uc.GetProduct(factory, alice).execute(skyr).portions}
    assert portions[small].is_default and not portions[big.id].is_default
    uc.UpdatePortion(factory, alice).execute(small, {"is_default": False})
    assert not any(p.is_default for p in uc.GetProduct(factory, alice).execute(skyr).portions)


def test_t_svc_416_unit_conversion_and_batch_matching(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-416: an amount in the other unit without a density stays as given; a one-off
    consumable converts nothing; a cooked batch is a match candidate by its name."""
    honey = _product(factory, alice, "Honey")  # per 100 g, no density
    with factory(alice) as uow:
        row = uow.products.get(honey)
        assert row is not None
        assert uc.in_product_unit(row, 20, "ml") == (20, "ml")
        consumable = uow.products.get_consumable(honey)
        assert consumable is not None
        one_off = SimpleNamespace(kind="one_off", id=consumable.id)
        assert uc.in_reference_unit(uow, one_off, 3, "ml") == (3, "ml")  # type: ignore[arg-type]

    stew = recipe_uc.CreateRecipe(factory, alice).execute("Lentil stew")
    recipe_uc.CookBatch(factory, alice).execute(stew.id, cooked_at=DAY, total_weight_g=1000)
    names = [c.name for c in uc.MatchText(factory, alice).execute("lentil stew")]
    assert any("Lentil stew" in n for n in names)


def test_t_svc_452_a_version_ignores_keys_that_are_no_values(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-452: a key in the changes that is not a product value is dropped, not stored."""
    tea = _product(factory, alice, "Black tea")
    fresh = uc.NewProductVersion(factory, alice).execute(tea, DAY, {"colour": "dark", "kcal": 1})
    assert fresh.kcal == 1
