"""Tenants and users (administration, CLI)."""

from __future__ import annotations

import re

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.use_cases._base import UseCase
from victus.infrastructure.auth import recovery
from victus.infrastructure.db import orm

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class CreateTenant(UseCase):
    """Not scoped: creates the tenant row itself. ``ctx`` may name any tenant."""

    def execute(self, slug: str, name: str) -> dto.TenantView:
        if not SLUG.match(slug):
            raise ValidationFailed("slug must be lowercase letters, digits and dashes")
        with self._uow() as uow:
            if uow.tenants.get_by_slug(slug) is not None:
                raise Conflict(f"tenant '{slug}' exists")
            t = uow.tenants.add(orm.Tenant(slug=slug, name=name or slug))
            view = dto.TenantView(id=t.id, slug=t.slug, name=t.name)
            uow.commit()
            return view


class CreateUser(UseCase):
    """Create a user in the context's tenant and return the one-time recovery code."""

    def execute(self, display_name: str, email: str, role: str = "member") -> dto.OwnerCreated:
        email = email.strip().lower()
        if "@" not in email:
            raise ValidationFailed("a valid e-mail address is required")
        if role not in ("owner", "member"):
            raise ValidationFailed("role must be owner or member")
        with self._uow() as uow:
            if uow.users.get_by_email(email) is not None:
                raise Conflict(f"user '{email}' exists in this tenant")
            code = recovery.generate_recovery_code()
            u = uow.users.add(
                orm.User(
                    tenant_id=self.ctx.tenant_id,
                    display_name=display_name,
                    email=email,
                    role=role,
                    recovery_code_hash=recovery.hash_recovery_code(code),
                )
            )
            uow.audit.record("user.create", "user", u.id, {"email": email, "role": role})
            view = dto.UserView(id=u.id, display_name=u.display_name, email=u.email, role=u.role)
            uow.commit()
            return dto.OwnerCreated(user=view, recovery_code=code)


class ResetRecoveryCode(UseCase):
    def execute(self, email: str) -> dto.OwnerCreated:
        with self._uow() as uow:
            u = uow.users.get_by_email(email.strip().lower())
            if u is None:
                raise NotFound(f"user '{email}' not found")
            code = recovery.generate_recovery_code()
            u.recovery_code_hash = recovery.hash_recovery_code(code)
            uow.audit.record("user.recovery_reset", "user", u.id, {})
            view = dto.UserView(id=u.id, display_name=u.display_name, email=u.email, role=u.role)
            uow.commit()
            return dto.OwnerCreated(user=view, recovery_code=code)


class ListUsers(UseCase):
    def execute(self) -> list[dto.UserView]:
        with self._uow() as uow:
            return [
                dto.UserView(id=u.id, display_name=u.display_name, email=u.email, role=u.role)
                for u in uow.users.list()
            ]


class GetTenant(UseCase):
    def execute(self) -> dto.TenantView:
        with self._uow() as uow:
            t = uow.tenants.get(self.ctx.tenant_id)
            if t is None:
                raise NotFound("tenant not found")
            return dto.TenantView(id=t.id, slug=t.slug, name=t.name)
