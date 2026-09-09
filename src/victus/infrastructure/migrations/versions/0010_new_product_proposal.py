"""A proposal may introduce a product that does not exist yet (R81).

``product_id`` becomes optional and a ``kind`` tells the two cases apart:
``update`` changes an existing product, ``new`` promotes the one-off consumable in
``consumable_id`` into a catalogue entry once a person approves.

Revision 0001 builds the schema from the mapped models, so a fresh database already has
the columns *and* their named constraints; every step below checks before it creates.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "product_proposal"
CHECK = "ck_product_proposal_kind"
FK = "fk_product_proposal_consumable"


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _checks() -> set[str]:
    return {
        name
        for c in sa.inspect(op.get_bind()).get_check_constraints(TABLE)
        if (name := c["name"]) is not None
    }


def _foreign_keys() -> set[str]:
    return {
        name
        for c in sa.inspect(op.get_bind()).get_foreign_keys(TABLE)
        if (name := c["name"]) is not None
    }


def upgrade() -> None:
    existing = _columns()
    with op.batch_alter_table(TABLE) as batch:
        if "kind" not in existing:
            batch.add_column(
                sa.Column("kind", sa.String(8), nullable=False, server_default="update")
            )
        if "consumable_id" not in existing:
            batch.add_column(sa.Column("consumable_id", sa.Integer(), nullable=True))
        batch.alter_column("product_id", existing_type=sa.Integer(), nullable=True)
    # Named constraints are created inside the batch copy only where the dialect keeps
    # them; SQLite rebuilds the table from the model, PostgreSQL needs the explicit step —
    # but only where revision 0001 did not already bring them along with the model.
    if op.get_bind().dialect.name == "postgresql":
        if CHECK not in _checks():
            op.create_check_constraint(CHECK, TABLE, "kind IN ('update','new')")
        if FK not in _foreign_keys():
            op.create_foreign_key(
                FK,
                TABLE,
                "consumable",
                ["consumable_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        if FK in _foreign_keys():
            op.drop_constraint(FK, TABLE, type_="foreignkey")
        if CHECK in _checks():
            op.drop_constraint(CHECK, TABLE, type_="check")
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE product_id IS NULL"))
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("product_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("consumable_id")
        batch.drop_column("kind")
