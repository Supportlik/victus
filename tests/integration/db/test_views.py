"""T-SVC-003: nutrients are computed by the views; quantities stay frozen, nutrients propagate."""

from __future__ import annotations

from datetime import date

import pytest

from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

from .conftest import add_item, make_day, make_product

pytestmark = pytest.mark.service


def test_day_macros_follow_product_correction(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        p = make_product(u, kcal=100.0, protein=10.0, salt=1.0)
        day = make_day(u, date(2026, 1, 10))
        add_item(u, day, p.id, 250)
        u.commit()

        m = u.day_logs.macros_for(date(2026, 1, 10))
        assert m is not None
        assert m.kcal == 250 and m.protein == 25.0 and m.salt == 2.5

        p.kcal = 120.0  # label correction → every historical day changes …
        u.commit()
        m2 = u.day_logs.macros_for(date(2026, 1, 10))
        assert m2 is not None and m2.kcal == 300

        item = u.day_logs.get_line_item(next(iter(u.day_logs.line_item_macros(date(2026, 1, 10)))))
        assert item is not None and item.base_amount == 250  # … but the frozen quantity does not


def test_countable_days_filter(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        p = make_product(u)
        for d, reliable, status in (
            (date(2026, 1, 1), True, "closed"),
            (date(2026, 1, 2), False, "closed"),
            (date(2026, 1, 3), True, "open"),
            (date(2026, 1, 4), None, "closed"),
        ):
            day = make_day(u, d, reliable=reliable, status=status)
            add_item(u, day, p.id, 100)
        u.commit()
        assert u.day_logs.countable_days() == [date(2026, 1, 1)]


def test_recipe_batch_and_ad_hoc_in_per100_view(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        r = u.recipes.add(orm.Recipe(tenant_id=u.ctx.tenant_id, name="Lentil curry"))
        batch = u.recipes.add_recipe_batch(
            r,
            "Lentil curry (batch)",
            cooked_at=date(2026, 1, 3),
            total_weight_g=2000,
            kcal_total=3000,
            protein_total=150,
        )
        ad_hoc = u.products.add_ad_hoc_item("Restaurant pizza", kcal=250.0, protein=11.0)
        day = make_day(u, date(2026, 1, 12))
        add_item(u, day, batch.id, 500, position=1)
        add_item(u, day, ad_hoc.id, 300, position=2)
        u.commit()
        m = u.day_logs.macros_for(date(2026, 1, 12))
        assert m is not None
        assert m.kcal == 3000 * 500 / 2000 + 250 * 3  # 750 + 750
        assert m.protein == round(150 * 500 / 2000 + 11 * 3, 1)


def test_source_check_flags_deviation(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        p = make_product(u, kcal=100.0)
        good = make_day(u, date(2026, 1, 20), source_kcal=100.0)
        bad = make_day(u, date(2026, 1, 21), source_kcal=200.0)
        add_item(u, good, p.id, 100)
        add_item(u, bad, p.id, 100)
        u.commit()
        from sqlalchemy import text

        flagged = (
            u.session.execute(
                text("SELECT date FROM source_check WHERE tenant_id = :t"), {"t": u.ctx.tenant_id}
            )
            .scalars()
            .all()
        )
        assert [str(d)[:10] for d in flagged] == ["2026-01-21"]
