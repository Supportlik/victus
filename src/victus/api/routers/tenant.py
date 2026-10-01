"""Tenant and its users (owner sessions and ``admin`` tokens only)."""

from __future__ import annotations

from fastapi import APIRouter, status

from victus.api.deps import Ctx, Uow
from victus.api.schemas.auth import TenantOut, UserCreatedOut, UserOut
from victus.api.schemas.requests import UserIn
from victus.application.use_cases import tenants as uc

router = APIRouter(tags=["tenant"])


@router.get("/tenant", response_model=TenantOut)
def get_tenant(ctx: Ctx, uow: Uow) -> TenantOut:
    return TenantOut.model_validate(uc.GetTenant(uow, ctx).execute())


@router.get("/tenant/users", response_model=list[UserOut])
def list_users(ctx: Ctx, uow: Uow) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in uc.ListUsers(uow, ctx).execute()]


@router.post("/tenant/users", response_model=UserCreatedOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserIn, ctx: Ctx, uow: Uow) -> UserCreatedOut:
    # CreateUser checks ``admin`` itself, for a session and a token alike.
    created = uc.CreateUser(uow, ctx).execute(body.display_name, body.email, body.role)
    return UserCreatedOut(
        user=UserOut.model_validate(created.user), recovery_code=created.recovery_code
    )
