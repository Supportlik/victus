"""T-SVC-400…403: recipes, their ingredients and cooked batches through the use cases."""

from __future__ import annotations

from datetime import date

import pytest

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import recipes as uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.service


def _oil(factory: UowFactory, alice: TenantContext, *, density: float | None) -> int:
    """900 kcal per 100 g; with a density a millilitre amount converts to grams."""
    return (
        products_uc.CreateProduct(factory, alice)
        .execute(
            products_uc.ProductInput(
                name="Sunflower oil",
                kcal=900,
                protein=0,
                carbs=0,
                fat=100,
                fiber=0,
                salt=0,
                density_g_per_ml=density,
            )
        )
        .id
    )


def test_recipe_crud_and_its_guards(factory: UowFactory, alice: TenantContext, skyr: int) -> None:
    """T-SVC-400: create, list, read and rename a recipe; blanks, twins and unknown ids refused."""
    with pytest.raises(ValidationFailed):
        uc.CreateRecipe(factory, alice).execute("   ")
    bowl = uc.CreateRecipe(factory, alice).execute(" Skyr bowl ", default_servings=2)
    assert (bowl.name, bowl.default_servings, bowl.ingredients) == ("Skyr bowl", 2, [])
    with pytest.raises(Conflict):
        uc.CreateRecipe(factory, alice).execute("Skyr bowl")
    other = uc.CreateRecipe(factory, alice).execute("Porridge")

    uc.SetIngredients(factory, alice).execute(
        bowl.id,
        [
            uc.IngredientInput(product_id=skyr, amount=200, unit_code="g"),
            uc.IngredientInput(free_text="a pinch of cinnamon"),
        ],
    )
    listed = {r.name: r for r in uc.ListRecipes(factory, alice).execute()}
    assert set(listed) == {"Skyr bowl", "Porridge"}
    names = [(i.position, i.product_name, i.free_text) for i in listed["Skyr bowl"].ingredients]
    assert names == [(1, "Skyr natural", None), (2, None, "a pinch of cinnamon")]

    got = uc.GetRecipe(factory, alice).execute(bowl.id)
    assert [i.product_id for i in got.ingredients] == [skyr, None]
    with pytest.raises(NotFound):
        uc.GetRecipe(factory, alice).execute(999_999)

    with pytest.raises(Conflict):
        uc.UpdateRecipe(factory, alice).execute(bowl.id, {"name": "Porridge"})
    same = uc.UpdateRecipe(factory, alice).execute(bowl.id, {"name": "Skyr bowl"})
    assert same.name == "Skyr bowl", "renaming a recipe to its own name is not a clash"
    renamed = uc.UpdateRecipe(factory, alice).execute(
        bowl.id, {"name": "Breakfast bowl", "default_servings": None}
    )
    assert (renamed.name, renamed.default_servings) == ("Breakfast bowl", None)
    assert len(renamed.ingredients) == 2
    untouched = uc.UpdateRecipe(factory, alice).execute(other.id, {})
    assert (untouched.name, untouched.default_servings) == ("Porridge", None)
    with pytest.raises(NotFound):
        uc.UpdateRecipe(factory, alice).execute(999_999, {"name": "x"})


def test_ingredient_amounts_resolve_through_units_and_portions(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-401: grams, a named portion, the default portion of a unit and a density."""
    oil = _oil(factory, alice, density=0.9)
    recipe = uc.CreateRecipe(factory, alice).execute("Dressing", default_servings=4)
    tub_id = products_uc.GetProduct(factory, alice).execute(skyr).portions[0].id
    oil_tbsp = products_uc.AddPortion(factory, alice).execute(
        oil, products_uc.PortionInput(unit_code="tbsp", label="tbsp", amount=10)
    )
    uc.SetIngredients(factory, alice).execute(
        recipe.id,
        [
            # 1 kg → 1000 g of skyr = 630 kcal
            uc.IngredientInput(product_id=skyr, amount=1, unit_code="kg"),
            # the named portion: 1 tub = 400 g = 252 kcal
            uc.IngredientInput(product_id=skyr, amount=1, unit_code="tub", portion_id=tub_id),
            # a portion id that is not this product's falls back to the unit's default
            uc.IngredientInput(
                product_id=skyr, amount=0.5, unit_code="tub", portion_id=oil_tbsp.id
            ),
            # 100 ml of oil at 0.9 g/ml = 90 g = 810 kcal
            uc.IngredientInput(product_id=oil, amount=100, unit_code="ml"),
        ],
    )
    batch = uc.CookBatch(factory, alice).execute(
        recipe.id, cooked_at=date(2026, 3, 1), total_weight_g=1500
    )
    assert batch.kcal == pytest.approx(630 + 252 + 126 + 810)
    assert batch.fat == pytest.approx(10 * 0.2 + 4 * 0.2 + 2 * 0.2 + 90)
    assert batch.servings == 4, "servings default to the recipe's"
    assert batch.name == "Dressing (2026-03-01)"


def test_ingredients_without_a_resolvable_amount_count_nothing(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-402: free text, a unit with no portion, and unknown ids are handled, not guessed."""
    recipe = uc.CreateRecipe(factory, alice).execute("Mystery")
    with pytest.raises(NotFound):
        uc.SetIngredients(factory, alice).execute(999_999, [])
    with pytest.raises(NotFound):
        uc.SetIngredients(factory, alice).execute(
            recipe.id, [uc.IngredientInput(product_id=999_999, amount=1, unit_code="g")]
        )
    products_uc.AddPortion(factory, alice).execute(
        skyr, products_uc.PortionInput(unit_code="cup", label="cup", amount=250)
    )
    uc.SetIngredients(factory, alice).execute(
        recipe.id,
        [
            uc.IngredientInput(product_id=skyr, unit_code="g"),  # no amount
            uc.IngredientInput(product_id=skyr, amount=2, unit_code="bowl"),  # no portion
            uc.IngredientInput(product_id=skyr, amount=1, unit_code="cup"),  # not a default
            uc.IngredientInput(amount=50, unit_code="g", free_text="nuts"),  # no product
            uc.IngredientInput(amount=1, unit_code="cup", free_text="berries"),  # neither
            uc.IngredientInput(product_id=skyr, amount=100, unit_code="g"),  # the one that counts
        ],
    )
    view = uc.GetRecipe(factory, alice).execute(recipe.id)
    assert [i.position for i in view.ingredients] == [1, 2, 3, 4, 5, 6]
    batch = uc.CookBatch(factory, alice).execute(
        recipe.id, cooked_at=None, total_weight_g=None, servings=1, note="test"
    )
    assert batch.kcal == pytest.approx(63), "only the 100 g of skyr has a weight to count"
    assert (batch.name, batch.servings, batch.cooked_at) == ("Mystery (batch)", 1, None)


def test_batches_are_read_back_and_the_first_cooking_day_stays(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, skyr: int
) -> None:
    """T-SVC-403: a batch is found by id in its own tenant only; cooking twice adds a batch."""
    recipe = uc.CreateRecipe(factory, alice).execute("Skyr pot")
    uc.SetIngredients(factory, alice).execute(
        recipe.id, [uc.IngredientInput(product_id=skyr, amount=400, unit_code="g")]
    )
    with pytest.raises(NotFound):
        uc.CookBatch(factory, alice).execute(999_999, cooked_at=None, total_weight_g=None)
    first = uc.CookBatch(factory, alice).execute(
        recipe.id, cooked_at=date(2026, 3, 1), total_weight_g=400
    )
    second = uc.CookBatch(factory, alice).execute(
        recipe.id, cooked_at=date(2026, 3, 8), total_weight_g=400
    )
    assert first.id != second.id and first.kcal == second.kcal == pytest.approx(252)
    assert [b.id for b in uc.GetRecipe(factory, alice).execute(recipe.id).batches] == [
        first.id,
        second.id,
    ]
    assert uc.GetBatch(factory, alice).execute(second.id).cooked_at == date(2026, 3, 8)
    with pytest.raises(NotFound):
        uc.GetBatch(factory, bob).execute(first.id)
