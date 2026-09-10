"""A proposal may say that a product's values changed from a day on (R81, ADR 0013).

``kind='version'`` carries ``valid_from`` next to the changed fields, so an actor that
reads a new label can draft "the recipe changed on this date". Until now it could only
propose a correction to the current version, which rewrites what the days before that
change already counted. Only the CHECK on ``kind`` has to give way: the column is
``String(8)`` and ``version`` is seven characters.

Revision 0001 builds the schema from the mapped models, so a database created after this
revision was written already carries the widened constraint, and a SQLite database older
than revision 0010 carries the ``kind`` column with no constraint at all — 0010 could
only name it on PostgreSQL. All three states are ordinary, so the step below reads what
is there before it changes anything; PostgreSQL is the dialect that says so out loud,
where a second ``ADD CONSTRAINT`` of the same name fails while SQLite rebuilds happily.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "product_proposal"
KIND_CHECK = "ck_product_proposal_kind"
STATUS_CHECK = "ck_product_proposal_status"
STATUS = "status IN ('pending','approved','rejected')"
NARROW = "kind IN ('update','new')"
WIDE = "kind IN ('update','new','version')"
VERSION = "version"

TENANT_STATUS_INDEX = "ix_product_proposal_tenant_status"
PRODUCT_INDEX = "ix_product_proposal_product"


def _kind_check() -> str | None:
    """The expression the ``kind`` CHECK holds now, or ``None`` where there is none."""
    for c in sa.inspect(op.get_bind()).get_check_constraints(TABLE):
        if c["name"] == KIND_CHECK:
            return str(c["sqltext"])
    return None


def _frozen(kind_check: str | None) -> sa.Table:
    """``product_proposal`` as this revision finds it, spelled out for the SQLite rebuild.

    SQLite cannot alter a CHECK, so the table is recreated from whatever the batch is
    told it looks like. That is ``copy_from`` rather than reflection because reflection
    recovers a CHECK by parsing the stored ``CREATE TABLE`` text: it does report both of
    them here today, and the day it stops matching it would drop
    ``ck_product_proposal_status`` and say nothing. Spelling the table out also keeps the
    two indexes and the four foreign keys, ``ON DELETE`` included, out of that bet.
    """
    args: list[Any] = [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("product.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("consumable_id", sa.Integer, sa.ForeignKey("consumable.id", ondelete="CASCADE")),
        sa.Column("capture_id", sa.String(32), sa.ForeignKey("capture.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.String(32)),
        sa.Column("changes", sa.JSON, nullable=False),
        sa.Column("rationale", sa.Text),
        sa.Column("source", sa.String(300)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.String(32)),
        sa.CheckConstraint(STATUS, name=STATUS_CHECK),
        sa.Index(TENANT_STATUS_INDEX, "tenant_id", "status"),
        sa.Index(PRODUCT_INDEX, "product_id"),
    ]
    if kind_check is not None:
        args.append(sa.CheckConstraint(kind_check, name=KIND_CHECK))
    return sa.Table(TABLE, sa.MetaData(), *args)


def _set_kind_check(*, allow_version: bool) -> None:
    """Make the ``kind`` CHECK list exactly the kinds this revision allows."""
    listed = _kind_check()
    if listed is not None and (f"'{VERSION}'" in listed) == allow_version:
        return
    wanted = WIDE if allow_version else NARROW
    if op.get_bind().dialect.name == "postgresql":
        if listed is not None:
            op.drop_constraint(KIND_CHECK, TABLE, type_="check")
        op.create_check_constraint(KIND_CHECK, TABLE, wanted)
        return
    with op.batch_alter_table(TABLE, copy_from=_frozen(listed), recreate="always") as batch:
        if listed is not None:
            batch.drop_constraint(KIND_CHECK, type_="check")
        batch.create_check_constraint(KIND_CHECK, wanted)


def upgrade() -> None:
    _set_kind_check(allow_version=True)


def downgrade() -> None:
    # A version proposal has no narrower form: dropping the rows is the only way back.
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE kind = :kind").bindparams(kind=VERSION))
    _set_kind_check(allow_version=False)
