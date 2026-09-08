"""Use-case plumbing: one unit of work per execution, tenant context mandatory."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import TenantContext

UowFactory = Callable[[TenantContext], UnitOfWork]


class UseCase:
    """Base class. Subclasses implement ``execute(...)`` and open exactly one
    unit of work through :meth:`_uow`; they commit explicitly."""

    def __init__(self, uow_factory: UowFactory, ctx: TenantContext) -> None:
        self.uow_factory = uow_factory
        self.ctx = ctx

    def _uow(self) -> UnitOfWork:
        return self.uow_factory(self.ctx)


def now() -> datetime:
    return datetime.now(UTC)
