"""Use-case plumbing: one unit of work per execution, tenant context mandatory."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_APPROVE, SCOPE_WRITE, TenantContext

UowFactory = Callable[[TenantContext], UnitOfWork]


class UseCase:
    """Base class. Subclasses implement ``execute(...)`` and open exactly one
    unit of work through :meth:`_uow`; they commit explicitly."""

    def __init__(self, uow_factory: UowFactory, ctx: TenantContext) -> None:
        self.uow_factory = uow_factory
        self.ctx = ctx

    def _uow(self) -> UnitOfWork:
        return self.uow_factory(self.ctx)


def require_decision(ctx: TenantContext) -> None:
    """A decision is a write *and* the right to sign it off (SPEC R81).

    Both scopes are checked, write first, so a read-only caller still learns that it
    lacks ``write`` rather than being told about a scope it could never reach.
    """
    ctx.require(SCOPE_WRITE)
    ctx.require(SCOPE_APPROVE)


def now() -> datetime:
    return datetime.now(UTC)
