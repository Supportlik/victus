"""Tenant settings (versioned, schema-validated) and target bands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import jsonschema

from victus.application import dto
from victus.application.errors import NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.schemas_loader import load_schema
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase
from victus.application.use_cases._mappers import target_band_view
from victus.domain.services.calendar import DEFAULT_TIMEZONE, today_in
from victus.infrastructure.db import orm


@dataclass(frozen=True, slots=True)
class Regional:
    """The tenant's day boundary and its way of writing numbers (R69)."""

    timezone: str
    locale: str


def regional_of(uow: UnitOfWork, fallback: Regional | None = None) -> Regional:
    """Read the tenant's regional settings, falling back to the server defaults."""
    base = fallback or Regional(DEFAULT_TIMEZONE, "de-DE")
    current = uow.settings.current()
    data: dict[str, Any] = dict(current.data) if current is not None else {}
    section = data.get("regional")
    if not isinstance(section, dict):
        return base
    tz = section.get("timezone")
    loc = section.get("locale")
    return Regional(
        str(tz) if isinstance(tz, str) and tz else base.timezone,
        str(loc) if isinstance(loc, str) and loc else base.locale,
    )


BAND_KEYS = ("min", "opt_min", "opt_max", "target", "max")
MACRO_PREFIXES = ("kcal", "protein", "carbs", "fat", "fiber", "salt")


def validate_settings(data: dict[str, Any]) -> None:
    schema = load_schema("tenant-settings")
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise ValidationFailed(
            "tenant settings do not match the schema",
            errors=[
                {"field": "/".join(str(p) for p in e.path) or "$", "message": e.message}
                for e in errors
            ],
        )


def _settings_view(row: orm.TenantSettings) -> dto.SettingsVersionView:
    return dto.SettingsVersionView(
        version=row.version, valid_from=row.valid_from, data=row.data, changed_by=row.changed_by
    )


class GetSettings(UseCase):
    def execute(self) -> dto.SettingsVersionView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            row = uow.settings.current()
            if row is None:
                raise NotFound("no tenant settings yet")
            return _settings_view(row)


class SettingsVersions(UseCase):
    def execute(self) -> list[dto.SettingsVersionView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [_settings_view(r) for r in uow.settings.versions()]


def _band_fields(
    spec: dict[str, Any] | None, prefix: str, with_stretch: bool
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in BAND_KEYS:
        out[f"{prefix}_{k}"] = float(spec[k]) if spec and k in spec else None
    if with_stretch:
        out[f"{prefix}_stretch"] = (
            float(spec["stretch"]) if spec and spec.get("stretch") is not None else None
        )
    return out


def sync_target_bands(uow: UnitOfWork, data: dict[str, Any]) -> int:
    """Upsert ``target_bands`` from a settings document by (valid_from, training_type)."""
    existing = {(b.valid_from, b.training_type): b for b in uow.target_bands.list()}
    count = 0
    for spec in data.get("target_bands", []):
        valid_from = date.fromisoformat(spec["valid_from"])
        training_type = spec.get("training_type")
        fields: dict[str, Any] = {
            "name": spec["name"],
            "training_type": training_type,
            "valid_from": valid_from,
            "valid_until": date.fromisoformat(spec["valid_until"])
            if spec.get("valid_until")
            else None,
            "note": spec.get("note"),
        }
        fields.update(_band_fields(spec.get("kcal"), "kcal", False))
        fields.update(_band_fields(spec.get("protein"), "protein", True))
        fields.update(_band_fields(spec.get("carbs"), "carbs", False))
        fields.update(_band_fields(spec.get("fat"), "fat", False))
        fields.update(_band_fields(spec.get("fiber"), "fiber", True))
        fields.update(_band_fields(spec.get("salt"), "salt", False))
        row = existing.get((valid_from, training_type))
        if row is None:
            uow.target_bands.add(orm.TargetBand(tenant_id=uow.ctx.tenant_id, **fields))
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        count += 1
    uow.flush()
    return count


class PutSettings(UseCase):
    def execute(
        self, data: dict[str, Any], valid_from: date | None = None
    ) -> dto.SettingsVersionView:
        self.ctx.require(SCOPE_WRITE)
        validate_settings(data)
        with self._uow() as uow:
            when = valid_from or today_in(regional_of(uow).timezone)
            row = uow.settings.add_version(data, when, self.ctx.actor_id)
            sync_target_bands(uow, data)
            uow.audit.record(
                "settings.put",
                "tenant_settings",
                str(row.version),
                {"valid_from": row.valid_from.isoformat()},
            )
            view = _settings_view(row)
            uow.commit()
            return view


class ListTargetBands(UseCase):
    def execute(self) -> list[dto.TargetBandView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [target_band_view(b) for b in uow.target_bands.list()]


class UpsertTargetBand(UseCase):
    def execute(self, spec: dict[str, Any]) -> dto.TargetBandView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            sync_target_bands(uow, {"target_bands": [spec]})
            row = next(
                b
                for b in uow.target_bands.list()
                if b.valid_from == date.fromisoformat(spec["valid_from"])
                and b.training_type == spec.get("training_type")
            )
            view = target_band_view(row)
            uow.commit()
            return view
