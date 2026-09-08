"""Tenant settings (versioned) and target bands."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import Out, TargetBandOut
from victus.api.schemas.requests import SettingsIn, TargetBandIn
from victus.application.use_cases import settings as uc

router = APIRouter(tags=["settings"])


class SettingsVersionOut(Out):
    version: int
    valid_from: date
    data: dict[str, Any]
    changed_by: str | None


@router.get("/settings", response_model=SettingsVersionOut)
def get_settings(ctx: Ctx, uow: Uow) -> SettingsVersionOut:
    return SettingsVersionOut.model_validate(uc.GetSettings(uow, ctx).execute())


@router.put("/settings", response_model=SettingsVersionOut)
def put_settings(body: SettingsIn, ctx: Ctx, uow: Uow) -> SettingsVersionOut:
    return SettingsVersionOut.model_validate(
        uc.PutSettings(uow, ctx).execute(body.data, body.valid_from)
    )


@router.get("/settings/versions", response_model=list[SettingsVersionOut])
def settings_versions(ctx: Ctx, uow: Uow) -> list[SettingsVersionOut]:
    return [SettingsVersionOut.model_validate(v) for v in uc.SettingsVersions(uow, ctx).execute()]


@router.get("/target-bands", response_model=list[TargetBandOut])
def list_target_bands(ctx: Ctx, uow: Uow) -> list[TargetBandOut]:
    return [TargetBandOut.model_validate(asdict(b)) for b in uc.ListTargetBands(uow, ctx).execute()]


@router.post("/target-bands", response_model=TargetBandOut)
def upsert_target_band(body: TargetBandIn, ctx: Ctx, uow: Uow) -> TargetBandOut:
    spec = body.model_dump(mode="json", exclude_none=True)
    return TargetBandOut.model_validate(asdict(uc.UpsertTargetBand(uow, ctx).execute(spec)))
