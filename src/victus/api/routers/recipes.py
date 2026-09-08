"""Recipes, ingredients and batches."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, status
from pydantic import Field

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import MacrosOut, Out
from victus.api.schemas.requests import BatchIn, IngredientsIn, RecipeIn, RecipePatch
from victus.application.use_cases import recipes as uc

router = APIRouter(tags=["recipes"])


class IngredientOut(Out):
    id: int
    position: int
    product_id: int | None
    product_name: str | None
    amount: float | None
    unit_code: str | None
    free_text: str | None


class BatchOut(MacrosOut):
    id: int
    recipe_id: int
    name: str
    cooked_at: date | None
    servings: int | None
    total_weight_g: float | None
    finished_at: date | None


class RecipeOut(Out):
    id: int
    name: str
    default_servings: int | None
    ingredients: list[IngredientOut] = Field(default_factory=list)
    batches: list[BatchOut] = Field(default_factory=list)


def _out(r: object) -> RecipeOut:
    return RecipeOut.model_validate(asdict(r))  # type: ignore[call-overload]


@router.get("/recipes", response_model=list[RecipeOut])
def list_recipes(ctx: Ctx, uow: Uow) -> list[RecipeOut]:
    return [_out(r) for r in uc.ListRecipes(uow, ctx).execute()]


@router.post("/recipes", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(body: RecipeIn, ctx: Ctx, uow: Uow) -> RecipeOut:
    return _out(uc.CreateRecipe(uow, ctx).execute(body.name, body.default_servings))


@router.get("/recipes/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: int, ctx: Ctx, uow: Uow) -> RecipeOut:
    return _out(uc.GetRecipe(uow, ctx).execute(recipe_id))


@router.patch("/recipes/{recipe_id}", response_model=RecipeOut)
def update_recipe(recipe_id: int, body: RecipePatch, ctx: Ctx, uow: Uow) -> RecipeOut:
    return _out(uc.UpdateRecipe(uow, ctx).execute(recipe_id, body.model_dump(exclude_unset=True)))


@router.put("/recipes/{recipe_id}/ingredients", response_model=RecipeOut)
def set_ingredients(recipe_id: int, body: IngredientsIn, ctx: Ctx, uow: Uow) -> RecipeOut:
    ingredients = [uc.IngredientInput(**i.model_dump()) for i in body.ingredients]
    return _out(uc.SetIngredients(uow, ctx).execute(recipe_id, ingredients))


@router.post(
    "/recipes/{recipe_id}/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED
)
def cook_batch(recipe_id: int, body: BatchIn, ctx: Ctx, uow: Uow) -> BatchOut:
    b = uc.CookBatch(uow, ctx).execute(
        recipe_id,
        cooked_at=body.cooked_at,
        total_weight_g=body.total_weight_g,
        servings=body.servings,
        note=body.note,
    )
    return BatchOut.model_validate(asdict(b))


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: int, ctx: Ctx, uow: Uow) -> BatchOut:
    return BatchOut.model_validate(asdict(uc.GetBatch(uow, ctx).execute(batch_id)))
