"""T-OPS-005, T-OPS-017, T-OPS-018: migration to head on an empty and on a populated database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.integration.db.conftest import TEST_URL
from victus.domain.services.units import UNITS as DOMAIN_UNITS
from victus.infrastructure.db import views
from victus.infrastructure.db.engine import make_engine
from victus.infrastructure.migrations import runner
from victus.infrastructure.migrations.units_seed import UNITS

pytestmark = pytest.mark.service


def test_upgrade_reaches_head_and_is_idempotent(engine: Engine) -> None:
    assert runner.current(engine=engine) == runner.head() == "0012"
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


def test_transcripts_are_attributed_to_a_recording_when_upgrading() -> None:
    """T-OPS-017: 0011 gives the rows that predate ``attachment_id`` their recording.

    An existing database holds transcripts keyed only to the capture. The upgrade
    attributes each to the capture's first recording, which is the only part that was
    ever sent to a provider, so the card can print it under that player.
    """
    eng = make_engine(TEST_URL)
    try:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        runner.upgrade(engine=eng, revision="0010")
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenant (id, slug, name, active, created_at)"
                    " VALUES (:i,:s,:n,true,:t)"
                ),
                {"i": "t1", "s": "alice", "n": "Alice", "t": datetime(2026, 1, 5, tzinfo=UTC)},
            )
            for att, mime in (("att_photo", "image/jpeg"), ("att_1", "audio/webm")):
                conn.execute(
                    text(
                        "INSERT INTO attachment"
                        " (id, tenant_id, sha256, mime, size, storage_key, created_at)"
                        " VALUES (:i,'t1',:h,:m,10,:k,:t)"
                    ),
                    {
                        "i": att,
                        "h": att,
                        "m": mime,
                        "k": f"blobs/{att}",
                        "t": datetime(2026, 1, 5, tzinfo=UTC),
                    },
                )
            conn.execute(
                text(
                    "INSERT INTO capture"
                    " (id, tenant_id, kind, captured_at, status, attachment_id, content_hash)"
                    " VALUES ('c1','t1','audio',:t,'new','att_photo','hash1')"
                ),
                {"t": datetime(2026, 1, 5, tzinfo=UTC)},
            )
            # the photo arrived first, so it is the one `capture.attachment_id` names
            for att, pos in (("att_photo", 1), ("att_1", 2)):
                conn.execute(
                    text(
                        "INSERT INTO capture_attachment (capture_id, attachment_id, position)"
                        " VALUES ('c1',:a,:p)"
                    ),
                    {"a": att, "p": pos},
                )
            conn.execute(
                text(
                    "INSERT INTO transcript (capture_id, provider, model, text, created_at)"
                    " VALUES ('c1','openai','gpt-4o-transcribe','a whole tub of skyr',:t)"
                ),
                {"t": datetime(2026, 1, 5, tzinfo=UTC)},
            )

        runner.upgrade(engine=eng)
        with eng.connect() as conn:
            assert (
                conn.execute(text("SELECT attachment_id FROM transcript")).scalar_one() == "att_1"
            )
    finally:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        eng.dispose()


PROPOSAL = text(
    "INSERT INTO product_proposal (id, tenant_id, kind, changes, status, created_at)"
    " VALUES (:i,'t1',:k,'{}',:s,:t)"
)


def _proposal(conn: object, ident: str, kind: str, status: str = "pending") -> None:
    conn.execute(  # type: ignore[attr-defined]
        PROPOSAL,
        {"i": ident, "k": kind, "s": status, "t": datetime(2026, 1, 5, tzinfo=UTC)},
    )


def test_t_ops_018_the_proposal_kind_check_widens_and_the_table_survives_it() -> None:
    """T-OPS-018: 0012 widens one CHECK, and on SQLite that means rebuilding the table.

    SQLite cannot alter a CHECK, so the table is recreated — and a rebuild drops
    everything it was not told about. ``ck_product_proposal_status``, both indexes and
    the four foreign keys therefore have to come out the other side, and the rows with
    them. A database *created* at this revision already has the wide constraint, because
    revision 0001 builds the schema from the models; the narrow one only exists on a
    database older than this revision, which the downgrade produces.
    """
    eng = make_engine(TEST_URL)
    try:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        runner.upgrade(engine=eng)
        runner.downgrade(engine=eng, revision="0011")

        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenant (id, slug, name, active, created_at)"
                    " VALUES ('t1','alice','Alice',true,:t)"
                ),
                {"t": datetime(2026, 1, 5, tzinfo=UTC)},
            )
            _proposal(conn, "p_update", "update")
        with pytest.raises(IntegrityError), eng.begin() as conn:  # an older database refuses
            _proposal(conn, "p_version", "version")

        runner.upgrade(engine=eng)

        insp = inspect(eng)
        checks = {
            c["name"]: str(c["sqltext"]) for c in insp.get_check_constraints("product_proposal")
        }
        assert "version" in checks["ck_product_proposal_kind"]
        assert "rejected" in checks["ck_product_proposal_status"], "the CHECK nobody touched"
        assert {i["name"] for i in insp.get_indexes("product_proposal")} >= {
            "ix_product_proposal_tenant_status",
            "ix_product_proposal_product",
        }
        assert {
            (f["referred_table"], f["constrained_columns"][0])
            for f in insp.get_foreign_keys("product_proposal")
        } == {
            ("tenant", "tenant_id"),
            ("product", "product_id"),
            ("consumable", "consumable_id"),
            ("capture", "capture_id"),
        }
        with eng.begin() as conn:
            _proposal(conn, "p_version", "version")
            kinds = conn.execute(
                text("SELECT id, kind FROM product_proposal ORDER BY id")
            ).fetchall()
        assert [tuple(r) for r in kinds] == [("p_update", "update"), ("p_version", "version")]
        with pytest.raises(IntegrityError), eng.begin() as conn:  # the CHECK nobody touched
            _proposal(conn, "p_bad", "update", status="nonsense")

        # Going back cannot represent a version proposal, so it drops those rows only.
        runner.downgrade(engine=eng, revision="0011")
        with eng.connect() as conn:
            left = conn.execute(text("SELECT id FROM product_proposal")).scalars().all()
        assert list(left) == ["p_update"]
    finally:
        if not TEST_URL.startswith("sqlite"):
            runner.downgrade(engine=eng, revision="base")
        eng.dispose()
