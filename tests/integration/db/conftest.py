"""Database fixtures.

Default: in-memory SQLite migrated to head. Set ``VICTUS_TEST_DATABASE_URL``
(e.g. ``postgresql+psycopg://victus:victus@localhost/victus_test``) to run the
same suite against PostgreSQL; the database is dropped to ``base`` afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from victus.application.tenant_context import TenantContext
from victus.infrastructure.db import orm
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.migrations import runner

pytestmark = pytest.mark.service

TEST_URL = os.environ.get("VICTUS_TEST_DATABASE_URL") or "sqlite://"


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine(TEST_URL)
    if not TEST_URL.startswith("sqlite"):
        runner.downgrade(engine=eng, revision="base")
    runner.upgrade(engine=eng)
    yield eng
    if not TEST_URL.startswith("sqlite"):
        runner.downgrade(engine=eng, revision="base")
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def tenants(session_factory: sessionmaker[Session]) -> tuple[TenantContext, TenantContext]:
    with session_factory() as s:
        a = orm.Tenant(slug="alice", name="Alice")
        b = orm.Tenant(slug="bob", name="Bob")
        s.add_all([a, b])
        s.commit()
        return TenantContext(tenant_id=a.id, user_id=None), TenantContext(
            tenant_id=b.id, user_id=None
        )


@pytest.fixture
def uow_for(
    session_factory: sessionmaker[Session],
) -> Callable[[TenantContext], SqlAlchemyUnitOfWork]:
    def make(ctx: TenantContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make


@pytest.fixture
def uow(
    uow_for: Callable[[TenantContext], SqlAlchemyUnitOfWork],
    tenants: tuple[TenantContext, TenantContext],
) -> SqlAlchemyUnitOfWork:
    return uow_for(tenants[0])


def now() -> datetime:
    return datetime.now(UTC)


def make_product(
    u: SqlAlchemyUnitOfWork, name: str = "Skyr natural", **fields: object
) -> orm.Product:
    defaults: dict[str, object] = {
        "kcal": 63.0,
        "protein": 11.0,
        "carbs": 4.0,
        "fat": 0.2,
        "fiber": 0.0,
        "salt": 0.1,
    }
    defaults.update(fields)
    return u.products.add_product(name, **defaults)


def make_day(u: SqlAlchemyUnitOfWork, day: date = date(2026, 1, 5), **fields: object) -> orm.DayLog:
    defaults: dict[str, object] = {"reliable": True, "status": "closed", "created_by_kind": "user"}
    defaults.update(fields)
    return u.day_logs.add(orm.DayLog(tenant_id=u.ctx.tenant_id, date=day, **defaults))  # type: ignore[arg-type]


def add_item(
    u: SqlAlchemyUnitOfWork,
    day_log: orm.DayLog,
    consumable_id: int,
    grams: float,
    position: int = 1,
) -> orm.LineItem:
    meal = u.day_logs.add_meal(orm.Meal(day_log_id=day_log.id, position=position, name="Meal"))
    return u.day_logs.add_line_item(
        orm.LineItem(
            meal_id=meal.id,
            position=1,
            consumable_id=consumable_id,
            unit_code="g",
            amount=grams,
            base_amount=grams,
            base_unit="g",
            origin="manual",
        )
    )
