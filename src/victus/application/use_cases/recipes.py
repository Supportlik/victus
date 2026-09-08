"""Recipes, ingredients and cooked batches (frozen totals)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase
from victus.application.use_cases._mappers import batch_view, product_macros, recipe_view
from victus.domain.services.nutrients import line_item_macros, macros_per_100, sum_macros
from victus.domain.services.units import base_factor
from victus.infrastructure.db import orm


@dataclass(frozen=True, slots=True)
class IngredientInput:
    product_id: int | None = None
    amount: float | None = None
    unit_code: str | None = None
    portion_id: int | None = None
    free_text: str | None = None
    amount_estimated: bool = False


def _names(uow: Any, recipe: orm.Recipe) -> dict[int, str]:
    names: dict[int, str] = {}
    for ing in recipe.ingredients:
        if ing.product_id is not None:
            p = uow.products.get(ing.product_id)
            if p is not None:
                names[ing.product_id] = p.name
    return names


class ListRecipes(UseCase):
    def execute(self) -> list[dto.RecipeView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [
                recipe_view(r, uow.recipes.batches_for(r.id), _names(uow, r))
                for r in uow.recipes.list()
            ]


class GetRecipe(UseCase):
    def execute(self, recipe_id: int) -> dto.RecipeView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            r = uow.recipes.get(recipe_id)
            if r is None:
                raise NotFound(f"recipe {recipe_id} not found")
            return recipe_view(r, uow.recipes.batches_for(r.id), _names(uow, r))


class CreateRecipe(UseCase):
    def execute(self, name: str, default_servings: int | None = None) -> dto.RecipeView:
        self.ctx.require(SCOPE_WRITE)
        if not name.strip():
            raise ValidationFailed("name is required")
        with self._uow() as uow:
            if uow.recipes.by_name(name) is not None:
                raise Conflict(f"recipe '{name}' exists")
            r = uow.recipes.add(
                orm.Recipe(
                    tenant_id=self.ctx.tenant_id,
                    name=name.strip(),
                    default_servings=default_servings,
                )
            )
            view = recipe_view(r)
            uow.commit()
            return view


class UpdateRecipe(UseCase):
    def execute(self, recipe_id: int, changes: dict[str, Any]) -> dto.RecipeView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            r = uow.recipes.get(recipe_id)
            if r is None:
                raise NotFound(f"recipe {recipe_id} not found")
            if changes.get("name"):
                other = uow.recipes.by_name(changes["name"])
                if other is not None and other.id != r.id:
                    raise Conflict("recipe name exists")
                r.name = changes["name"]
            if "default_servings" in changes:
                r.default_servings = changes["default_servings"]
            uow.flush()
            view = recipe_view(r, uow.recipes.batches_for(r.id), _names(uow, r))
            uow.commit()
            return view


def _base_for(uow: Any, ing: IngredientInput) -> tuple[float | None, str | None]:
    if ing.amount is None or ing.unit_code is None:
        return None, None
    factor = base_factor(ing.unit_code)
    if factor is not None:
        return ing.amount * factor[0], factor[1]
    if ing.portion_id is not None and ing.product_id is not None:
        for p in uow.products.portions_for(ing.product_id):
            if p.id == ing.portion_id:
                return ing.amount * p.amount, p.amount_unit
    if ing.product_id is not None:
        for p in uow.products.portions_for(ing.product_id):
            if p.unit_code == ing.unit_code and p.is_default:
                return ing.amount * p.amount, p.amount_unit
    return None, None


class SetIngredients(UseCase):
    def execute(self, recipe_id: int, ingredients: list[IngredientInput]) -> dto.RecipeView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            r = uow.recipes.get(recipe_id)
            if r is None:
                raise NotFound(f"recipe {recipe_id} not found")
            r.ingredients.clear()
            for pos, ing in enumerate(ingredients, start=1):
                if ing.product_id is not None and uow.products.get(ing.product_id) is None:
                    raise NotFound(f"product {ing.product_id} not found")
                base, base_unit = _base_for(uow, ing)
                r.ingredients.append(
                    orm.RecipeIngredient(
                        position=pos,
                        product_id=ing.product_id,
                        portion_id=ing.portion_id,
                        unit_code=ing.unit_code,
                        amount=ing.amount,
                        base_amount=base,
                        base_unit=base_unit,
                        amount_estimated=ing.amount_estimated,
                        free_text=ing.free_text,
                    )
                )
            uow.flush()
            view = recipe_view(r, uow.recipes.batches_for(r.id), _names(uow, r))
            uow.commit()
            return view


class CookBatch(UseCase):
    """Freeze the recipe's current nutrient totals into a batch (a consumable)."""

    def execute(
        self,
        recipe_id: int,
        *,
        cooked_at: date | None,
        total_weight_g: float | None,
        servings: int | None = None,
        note: str | None = None,
    ) -> dto.BatchView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            r = uow.recipes.get(recipe_id)
            if r is None:
                raise NotFound(f"recipe {recipe_id} not found")
            per_item = []
            for ing in r.ingredients:
                if ing.product_id is None or ing.base_amount is None:
                    continue
                p = uow.products.get(ing.product_id)
                if p is None:
                    continue
                per_item.append(
                    line_item_macros(
                        macros_per_100(product_macros(p), p.reference_amount), ing.base_amount
                    )
                )
            totals = sum_macros(per_item)
            label = f"{r.name} ({cooked_at.isoformat()})" if cooked_at else f"{r.name} (batch)"
            batch = uow.recipes.add_recipe_batch(
                r,
                label,
                cooked_at=cooked_at,
                servings=servings if servings is not None else r.default_servings,
                total_weight_g=total_weight_g,
                kcal_total=totals.kcal,
                protein_total=totals.protein,
                carbs_total=totals.carbs,
                fat_total=totals.fat,
                fiber_total=totals.fiber,
                salt_total=totals.salt,
                note=note,
            )
            if r.first_cooked_at is None and cooked_at is not None:
                r.first_cooked_at = cooked_at
            uow.audit.record("recipe.cook", "recipe_batch", str(batch.id), {"recipe_id": r.id})
            view = batch_view(batch)
            uow.commit()
            return view


class GetBatch(UseCase):
    def execute(self, batch_id: int) -> dto.BatchView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            b = uow.recipes.get_batch(batch_id)
            if b is None:
                raise NotFound(f"batch {batch_id} not found")
            return batch_view(b)
