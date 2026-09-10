"""T-SVC-083/084/086/109: an amount in the other unit is converted through the density (R75)."""

from __future__ import annotations

import pytest

from tests.integration.service.conftest import DAY
from victus.application import dto
from victus.application.errors import ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import day_logs as uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import recipes as recipes_uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service


def _log(
    factory: UowFactory, alice: TenantContext, consumable_id: int, amount: float, unit: str
) -> dto.LineItemView:
    uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    return uc.AddLineItem(factory, alice).execute(
        meal.id, uc.LineItemInput(consumable_id=consumable_id, amount=amount, unit_code=unit)
    )


def test_t_svc_083_a_portion_in_the_other_unit_is_converted(
    factory: UowFactory, alice: TenantContext
) -> None:
    """A syrup is sold by volume and spooned out by weight; 20 g is not 20 ml of it.

    260 kcal per 100 ml at 1.32 g/ml makes a 20 g spoonful 15.15 ml, so 39.4 kcal. Counted
    as if the units agreed it would be 52 kcal — a third too much, and nothing would say so.
    """
    syrup = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Maple syrup",
            reference_unit="ml",
            density_g_per_ml=1.32,
            kcal=260,
            protein=0,
            carbs=65,
            fat=0,
            fiber=0,
            salt=0.02,
        )
    )
    products_uc.AddPortion(factory, alice).execute(
        syrup.id,
        products_uc.PortionInput(
            unit_code="tbsp", label="tbsp", amount=20, amount_unit="g", is_default=True
        ),
    )

    item = _log(factory, alice, syrup.id, 1, "tbsp")
    assert item.base_unit == "ml", "the product's nutrients are stated per 100 ml"
    assert item.base_amount == pytest.approx(15.1515, abs=0.001)
    assert item.amount == 1 and item.unit_code == "tbsp", "what was eaten stays as entered"

    kcal = uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0].kcal
    assert kcal == pytest.approx(39.394, abs=0.01), "not 52 kcal"


def test_t_svc_083_an_amount_in_the_other_unit_is_converted_too(
    factory: UowFactory, alice: TenantContext
) -> None:
    """The same fault reaches a plain weight, and the same conversion settles it.

    Both directions are exercised: grams of a product stated per millilitre, and
    millilitres of one stated per gram.
    """
    syrup = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Maple syrup", reference_unit="ml", density_g_per_ml=1.32, kcal=260
        )
    )
    item = _log(factory, alice, syrup.id, 132, "g")
    assert (item.base_amount, item.base_unit) == (pytest.approx(100.0), "ml")
    assert uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0].kcal == pytest.approx(260)

    oil = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Olive oil", reference_unit="g", density_g_per_ml=0.92, kcal=884
        )
    )
    meal = uc.AddMeal(factory, alice).execute(DAY, "Lunch")
    poured = uc.AddLineItem(factory, alice).execute(
        meal.id, uc.LineItemInput(consumable_id=oil.id, amount=10, unit_code="ml")
    )
    assert (poured.base_amount, poured.base_unit) == (pytest.approx(9.2), "g")
    lunch = next(m for m in uc.GetDay(factory, alice).execute(DAY).meals if m.name == "Lunch")
    assert lunch.line_items[0].kcal == pytest.approx(81.328, abs=0.01)


def test_t_svc_086_a_recipe_ingredient_is_converted_before_the_batch_is_frozen(
    factory: UowFactory, alice: TenantContext
) -> None:
    """Cooking stores the totals for good, so a wrong unit there can never be recomputed."""
    oil = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Olive oil", reference_unit="g", density_g_per_ml=0.92, kcal=884
        )
    )
    recipe = recipes_uc.CreateRecipe(factory, alice).execute("Dressing", 4)
    recipes_uc.SetIngredients(factory, alice).execute(
        recipe.id, [recipes_uc.IngredientInput(product_id=oil.id, amount=200, unit_code="ml")]
    )
    batch = recipes_uc.CookBatch(factory, alice).execute(
        recipe.id, cooked_at=DAY, total_weight_g=200
    )
    assert batch.kcal == pytest.approx(1626.56, abs=0.01), "184 g of oil, not 200"


def test_t_svc_084_without_a_density_such_a_portion_is_still_refused(
    factory: UowFactory, alice: TenantContext
) -> None:
    """R75's only way out is a density, so without one the portion cannot be stored."""
    juice = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Apple juice", reference_unit="ml", kcal=46)
    )
    in_grams = products_uc.PortionInput(
        unit_code="glass", label="glass", amount=250, amount_unit="g"
    )
    with pytest.raises(ValidationFailed, match="density"):
        products_uc.AddPortion(factory, alice).execute(juice.id, in_grams)

    in_millilitres = products_uc.PortionInput(
        unit_code="glass", label="glass", amount=250, amount_unit="ml", is_default=True
    )
    portion = products_uc.AddPortion(factory, alice).execute(juice.id, in_millilitres)
    with pytest.raises(ValidationFailed, match="density"):
        products_uc.UpdatePortion(factory, alice).execute(portion.id, {"amount_unit": "g"})

    # With a density the same portion is accepted, and now it is also converted.
    products_uc.UpdateProduct(factory, alice).execute(juice.id, {"density_g_per_ml": 1.05})
    heavy = products_uc.AddPortion(factory, alice).execute(
        juice.id,
        products_uc.PortionInput(unit_code="cup", label="cup", amount=210, amount_unit="g"),
    )
    assert heavy.amount_unit == "g", "the portion keeps the unit it was measured in"
    item = _log(factory, alice, juice.id, 1, "cup")
    assert (item.base_amount, item.base_unit) == (pytest.approx(200.0), "ml")


def test_t_svc_109_the_view_carries_the_density_and_the_refusal_names_it(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-109: R75's way out is only a way out if a reader can see it and reach it.

    The value was writable and readable nowhere, so a page could not say whether a product
    had one, and the sentence that refuses a portion named a field nobody could find.
    """
    juice = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Apple juice", reference_unit="ml", kcal=46)
    )
    assert juice.density_g_per_ml is None, "nothing relates g and ml for this one yet"

    with pytest.raises(ValidationFailed) as refused:
        products_uc.AddPortion(factory, alice).execute(
            juice.id,
            products_uc.PortionInput(unit_code="glass", label="glass", amount=250, amount_unit="g"),
        )
    assert refused.value.errors == [
        {"field": "density_g_per_ml", "message": "set it to convert g into ml"}
    ], "the field is named where a client can act on it, not only in the sentence"

    updated = products_uc.UpdateProduct(factory, alice).execute(
        juice.id, {"density_g_per_ml": 1.05}
    )
    assert updated.density_g_per_ml == pytest.approx(1.05)
    fetched = products_uc.GetProduct(factory, alice).execute(juice.id)
    assert fetched.density_g_per_ml == pytest.approx(1.05), (
        "and reading it back shows it, which is what a page compares a proposal against"
    )
