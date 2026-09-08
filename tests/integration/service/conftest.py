"""Use-case fixtures: a factory that opens tenant-scoped units of work."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.tenant_context import TenantContext
from victus.application.use_cases import products as products_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork


@pytest.fixture
def factory(session_factory: sessionmaker[Session]) -> UowFactory:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make


@pytest.fixture
def alice(tenants: tuple[TenantContext, TenantContext]) -> TenantContext:
    return tenants[0]


@pytest.fixture
def bob(tenants: tuple[TenantContext, TenantContext]) -> TenantContext:
    return tenants[1]


@pytest.fixture
def skyr(factory: UowFactory, alice: TenantContext) -> int:
    """A product with a 400 g tub portion; returns its id."""
    p = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Skyr natural", kcal=63, protein=11, carbs=4, fat=0.2, fiber=0, salt=0.1
        )
    )
    products_uc.AddPortion(factory, alice).execute(
        p.id, products_uc.PortionInput(unit_code="tub", label="tub", amount=400, is_default=True)
    )
    return p.id


DAY = date(2026, 3, 10)

Make = Callable[[TenantContext], SqlAlchemyUnitOfWork]
