"""Units and categories."""

from __future__ import annotations

from fastapi import APIRouter, status

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import CategoryOut, UnitOut
from victus.api.schemas.requests import CategoryIn
from victus.application.use_cases import products as uc

router = APIRouter(tags=["master data"])


@router.get("/units", response_model=list[UnitOut])
def list_units(ctx: Ctx, uow: Uow) -> list[UnitOut]:
    return [UnitOut.model_validate(u) for u in uc.ListUnits(uow, ctx).execute()]


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(ctx: Ctx, uow: Uow) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in uc.ListCategories(uow, ctx).execute()]


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, ctx: Ctx, uow: Uow) -> CategoryOut:
    return CategoryOut.model_validate(uc.CreateCategory(uow, ctx).execute(body.name))
