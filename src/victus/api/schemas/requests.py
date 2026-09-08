"""Request bodies."""

from __future__ import annotations

import datetime as dt
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    icon: str | None = Field(None, max_length=8)
    brand: str | None = None
    category_id: int | None = None
    category: str | None = None
    reference_amount: float = Field(100.0, gt=0)
    reference_unit: Literal["g", "ml"] = "g"
    density_g_per_ml: float | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None
    source: str | None = None
    verified: bool = False
    ean: str | None = None
    note: str | None = None
    checked_at: date | None = None


class ProductPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=300)
    icon: str | None = Field(None, max_length=8)
    brand: str | None = None
    category_id: int | None = None
    category: str | None = None
    reference_amount: float | None = Field(None, gt=0)
    reference_unit: Literal["g", "ml"] | None = None
    density_g_per_ml: float | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None
    source: str | None = None
    verified: bool | None = None
    ean: str | None = None
    note: str | None = None
    checked_at: date | None = None


class PortionIn(BaseModel):
    unit_code: str
    label: str = Field(min_length=1, max_length=100)
    description: str | None = None
    amount: float = Field(gt=0)
    amount_unit: Literal["g", "ml"] = "g"
    is_default: bool = False
    weight_source: Literal["weighed", "estimated"] | None = None


class PortionPatch(BaseModel):
    unit_code: str | None = None
    label: str | None = None
    description: str | None = None
    amount: float | None = Field(None, gt=0)
    amount_unit: Literal["g", "ml"] | None = None
    is_default: bool | None = None
    weight_source: Literal["weighed", "estimated"] | None = None


class MatchIn(BaseModel):
    text: str = Field(min_length=1)
    limit: int = Field(5, ge=1, le=20)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    default_servings: int | None = Field(None, ge=1)


class RecipePatch(BaseModel):
    name: str | None = None
    default_servings: int | None = None


class IngredientIn(BaseModel):
    product_id: int | None = None
    amount: float | None = Field(None, ge=0)
    unit_code: str | None = None
    portion_id: int | None = None
    free_text: str | None = None
    amount_estimated: bool = False


class IngredientsIn(BaseModel):
    ingredients: list[IngredientIn]


class BatchIn(BaseModel):
    cooked_at: date | None = None
    servings: int | None = Field(None, ge=1)
    total_weight_g: float | None = Field(None, gt=0)
    note: str | None = None


class DayCreate(BaseModel):
    reliable: bool
    training_type: Literal["rest", "strength", "martial_arts"] | None = None
    notes: str | None = None


class DayFlags(BaseModel):
    reliable: bool | None = None
    training_type: Literal["rest", "strength", "martial_arts"] | None = None
    notes: str | None = None


class MealIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    time: dt.time | None = None


class MealPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    time: dt.time | None = None


class LineItemIn(BaseModel):
    consumable_id: int
    amount: float = Field(ge=0)
    unit_code: str
    portion_id: int | None = None
    estimated: bool = False
    amount_estimated: bool = False
    raw_text: str | None = None


class LineItemPatch(BaseModel):
    consumable_id: int | None = None
    amount: float | None = Field(None, ge=0)
    unit_code: str | None = None
    portion_id: int | None = None
    estimated: bool | None = None
    amount_estimated: bool | None = None


class DayMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DraftCorrectionIn(BaseModel):
    line_item_id: int
    amount: float | None = Field(None, ge=0)
    unit_code: str | None = None
    consumable_id: int | None = None
    delete: bool = False


class ApproveIn(BaseModel):
    corrections: list[DraftCorrectionIn] = []
    close: bool = True


class ApproveItemIn(BaseModel):
    """Corrections applied while accepting a single drafted item.

    ``meal_id`` moves it to another meal of that day; ``meal_name`` picks a meal by
    name and creates it when it does not exist yet.
    """

    amount: float | None = Field(default=None, ge=0)
    unit_code: str | None = None
    consumable_id: int | None = None
    meal_id: int | None = None
    meal_name: str | None = Field(default=None, max_length=200)


class WeightIn(BaseModel):
    measured_at: datetime
    kg: float = Field(gt=0)


class RuleIn(BaseModel):
    """One of the user's own instructions for the agent."""

    when: str = Field(min_length=1, max_length=300)
    then: str = Field(min_length=1, max_length=1000)
    name: str | None = Field(default=None, max_length=60)
    scope: Literal["products", "days", "reports", "all"] = "all"
    enabled: bool = True
    priority: int = 100


class SettingsIn(BaseModel):
    data: dict[str, Any]
    valid_from: date | None = None


class TargetBandIn(BaseModel):
    name: str
    training_type: Literal["rest", "strength", "martial_arts"] | None = None
    valid_from: date
    valid_until: date | None = None
    kcal: dict[str, float] | None = None
    protein: dict[str, float]
    carbs: dict[str, float]
    fat: dict[str, float]
    fiber: dict[str, float]
    salt: dict[str, float]
    note: str | None = None


# ── auth ──


class RegisterOptionsIn(BaseModel):
    name: str | None = None
    invitation: str | None = None


class RegisterVerifyIn(BaseModel):
    """The browser's attestation plus our ceremony id and the passkey label."""

    model_config = {"extra": "allow"}

    ceremony_id: str | None = None
    name: str | None = None


class LoginOptionsIn(BaseModel):
    email: str | None = None


class LoginVerifyIn(BaseModel):
    model_config = {"extra": "allow"}

    ceremony_id: str | None = None


class RecoveryIn(BaseModel):
    email: str
    code: str


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class UserIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: str
    role: Literal["owner", "member"] = "member"
