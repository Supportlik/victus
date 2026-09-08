"""T-SVC-016: repositories never leak rows across tenants."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from victus.application.tenant_context import TenantContext
from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import TenantMismatchError
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

from .conftest import add_item, make_day, make_product

pytestmark = pytest.mark.service


def test_t_svc_016_products_and_days_are_scoped(
    uow_for: Callable[[TenantContext], SqlAlchemyUnitOfWork],
    tenants: tuple[TenantContext, TenantContext],
) -> None:
    alice, bob = tenants
    with uow_for(alice) as u:
        p = make_product(u, "Skyr natural")
        day = make_day(u, date(2026, 2, 1))
        add_item(u, day, p.id, 400)
        u.commit()
        product_id, day_id = p.id, day.id

    with uow_for(bob) as u:
        assert u.products.get(product_id) is None
        assert u.products.search("skyr") == []
        assert u.products.all_names() == []
        assert u.day_logs.get(day_id) is None
        assert u.day_logs.get_by_date(date(2026, 2, 1)) is None
        assert u.day_logs.macros_for(date(2026, 2, 1)) is None
        assert u.day_logs.line_item_macros(date(2026, 2, 1)) == {}

    with uow_for(alice) as u:
        assert u.products.get(product_id) is not None
        assert [x.name for x in u.products.search("skyr")] == ["Skyr natural"]
        assert u.day_logs.get_by_date(date(2026, 2, 1)) is not None


def test_child_rows_follow_parent_scope(
    uow_for: Callable[[TenantContext], SqlAlchemyUnitOfWork],
    tenants: tuple[TenantContext, TenantContext],
) -> None:
    alice, bob = tenants
    with uow_for(alice) as u:
        p = make_product(u)
        day = make_day(u)
        item = add_item(u, day, p.id, 100)
        u.commit()
        item_id, meal_id, product_id = item.id, item.meal_id, p.id

    with uow_for(bob) as u:
        assert u.day_logs.get_line_item(item_id) is None
        assert u.day_logs.get_meal(meal_id) is None
        assert u.products.portions_for(product_id) == []
        with pytest.raises(PermissionError):
            u.day_logs.add_meal(orm.Meal(day_log_id=day.id, position=9))


def test_guard_rejects_foreign_entities(
    uow_for: Callable[[TenantContext], SqlAlchemyUnitOfWork],
    tenants: tuple[TenantContext, TenantContext],
) -> None:
    alice, bob = tenants
    with uow_for(alice) as u, pytest.raises(TenantMismatchError):
        u.day_logs.add(
            orm.DayLog(tenant_id=bob.tenant_id, date=date(2026, 3, 1), status="open", reliable=True)
        )
