"""T-OPS-005: migration to head on an empty database; unit seed; views present."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect, text

from victus.domain.services.units import UNITS as DOMAIN_UNITS
from victus.infrastructure.db import views
from victus.infrastructure.migrations import runner
from victus.infrastructure.migrations.units_seed import UNITS

pytestmark = pytest.mark.service


def test_upgrade_reaches_head_and_is_idempotent(engine: Engine) -> None:
    assert runner.current(engine=engine) == runner.head() == "0001"
    runner.upgrade(engine=engine)  # second run is a no-op
    assert runner.is_up_to_date(engine=engine)


def test_all_tables_and_views_exist(engine: Engine) -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for name in (
        "tenant",
        "user",
        "passkey_credential",
        "session",
        "api_token",
        "tenant_settings",
        "unit",
        "category",
        "consumable",
        "product",
        "portion",
        "recipe",
        "recipe_ingredient",
        "recipe_batch",
        "ad_hoc_item",
        "target_band",
        "day_log",
        "meal",
        "line_item",
        "weight_entry",
        "capture",
        "attachment",
        "transcript",
        "agent_run",
        "agent_session",
        "agent_lock",
        "day_message",
        "backup_job",
        "audit_log",
    ):
        assert name in tables, name
    assert set(insp.get_view_names()) >= set(views.VIEW_NAMES)


def test_unit_seed(engine: Engine) -> None:
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM unit")).scalar_one()
        fuzzy = (
            conn.execute(text("SELECT code FROM unit WHERE fuzzy = 1 ORDER BY code"))
            .scalars()
            .all()
        )
    assert n == len(UNITS) == len(DOMAIN_UNITS)
    assert fuzzy == sorted(c for c, u in DOMAIN_UNITS.items() if u.fuzzy)
