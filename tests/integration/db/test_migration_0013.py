"""T-SVC-311: revision 0013 adds the author and the original values of a proposal."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text

from tests.integration.db.conftest import TEST_URL
from victus.infrastructure.db.engine import make_engine
from victus.infrastructure.migrations import runner

pytestmark = pytest.mark.service

NEW_COLUMNS = {"created_by", "proposed_changes"}


def _columns(eng: object) -> set[str]:
    return {c["name"] for c in inspect(eng).get_columns("product_proposal")}  # type: ignore[arg-type]


def test_t_svc_311_the_columns_arrive_empty_and_leave_the_rows_behind() -> None:
    """T-SVC-311: an older row gains two NULL columns, the CHECKs survive, and back again.

    ``ADD COLUMN`` of a nullable column is the one change SQLite makes without rebuilding
    the table, so the status CHECK revision 0012 had to spell out is still there after it.
    """
    eng = make_engine(TEST_URL)
    try:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        runner.upgrade(engine=eng)
        assert _columns(eng) >= NEW_COLUMNS, "a fresh database is built from the models"
        runner.downgrade(engine=eng, revision="0012")
        assert not NEW_COLUMNS & _columns(eng)

        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenant (id, slug, name, active, created_at)"
                    " VALUES ('t1','alice','Alice',true,:t)"
                ),
                {"t": datetime(2026, 1, 5, tzinfo=UTC)},
            )
            conn.execute(
                text(
                    "INSERT INTO product_proposal"
                    " (id, tenant_id, kind, changes, status, created_at)"
                    " VALUES ('p1','t1','update','{\"kcal\": 70}','pending',:t)"
                ),
                {"t": datetime(2026, 1, 5, tzinfo=UTC)},
            )

        runner.upgrade(engine=eng)
        assert runner.current(engine=eng) == "0013"
        assert _columns(eng) >= NEW_COLUMNS
        checks = {c["name"] for c in inspect(eng).get_check_constraints("product_proposal")}
        assert {"ck_product_proposal_kind", "ck_product_proposal_status"} <= checks
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT created_by, proposed_changes FROM product_proposal WHERE id = 'p1'")
            ).one()
        assert tuple(row) == (None, None)

        runner.upgrade(engine=eng)  # a second run changes nothing
        runner.downgrade(engine=eng, revision="0012")
        with eng.connect() as conn:
            left = conn.execute(text("SELECT id FROM product_proposal")).scalars().all()
        assert list(left) == ["p1"]
        assert not NEW_COLUMNS & _columns(eng)
    finally:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        eng.dispose()
