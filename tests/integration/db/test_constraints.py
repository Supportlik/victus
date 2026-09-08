"""T-SVC-001/002 and schema invariants: FK pragma, subtype safety, default portion."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

from .conftest import add_item, make_day, make_product

pytestmark = pytest.mark.service


def test_t_svc_001_foreign_keys_are_enforced(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        day = make_day(u)
        with pytest.raises(IntegrityError):
            add_item(u, day, consumable_id=999_999, grams=100)


def test_t_svc_002_subtype_cannot_masquerade(uow: SqlAlchemyUnitOfWork) -> None:
    """A product row must point at a consumable of kind 'product'."""
    with uow as u:
        c = orm.Consumable(tenant_id=u.ctx.tenant_id, kind="recipe_batch", name="Batch")
        u.session.add(c)
        u.session.flush()
        u.session.add(orm.Product(id=c.id, kind="product", kcal=100.0))
        with pytest.raises(IntegrityError):
            u.session.flush()


def test_one_default_portion_per_product_and_unit(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        p = make_product(u)
        u.products.add_portion(
            orm.Portion(
                product_id=p.id,
                unit_code="tub",
                label="whole tub",
                amount=400,
                amount_unit="g",
                is_default=True,
            )
        )
        u.products.add_portion(
            orm.Portion(
                product_id=p.id,
                unit_code="tub",
                label="small tub",
                amount=150,
                amount_unit="g",
                is_default=False,
            )
        )
        with pytest.raises(IntegrityError):
            u.products.add_portion(
                orm.Portion(
                    product_id=p.id,
                    unit_code="tub",
                    label="another default",
                    amount=500,
                    amount_unit="g",
                    is_default=True,
                )
            )


def test_reliable_has_no_default(uow: SqlAlchemyUnitOfWork) -> None:
    """NULL stays NULL — the consistency check reports it; the schema adds no default."""
    with uow as u:
        day = u.day_logs.add(
            orm.DayLog(tenant_id=u.ctx.tenant_id, date=date(2026, 1, 6), status="open")
        )
        u.commit()
        assert day.reliable is None


def test_status_check_constraint(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u, pytest.raises(IntegrityError):
        u.day_logs.add(
            orm.DayLog(
                tenant_id=u.ctx.tenant_id, date=date(2026, 1, 7), status="bogus", reliable=True
            )
        )


def test_frozen_base_amount_is_required(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        p = make_product(u)
        day = make_day(u)
        meal = u.day_logs.add_meal(orm.Meal(day_log_id=day.id, position=1))
        with pytest.raises(IntegrityError):
            u.day_logs.add_line_item(
                orm.LineItem(
                    meal_id=meal.id, position=1, consumable_id=p.id, amount=1, unit_code="tub"
                )  # no base_amount
            )
