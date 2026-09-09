"""Products carry a validity range and a link to the version they replace (R70).

A recipe changes, a manufacturer reformulates, a shop swaps its supplier: the values of
"the same" product differ over time. Rather than overwriting them, which would silently
rewrite every day already logged, a new row covers the new period. ``valid_until`` stays
NULL for a product that is simply current, so nothing has to be maintained.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("valid_from", "valid_until", "supersedes_id")


def _present() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {c["name"] for c in inspector.get_columns("product")}


def upgrade() -> None:
    have = _present()
    with op.batch_alter_table("product") as batch:
        if "valid_from" not in have:
            # NULL means "as far back as the data goes", which is true of every existing row
            batch.add_column(sa.Column("valid_from", sa.Date(), nullable=True))
        if "valid_until" not in have:
            batch.add_column(sa.Column("valid_until", sa.Date(), nullable=True))
        if "supersedes_id" not in have:
            batch.add_column(sa.Column("supersedes_id", sa.Integer(), nullable=True))
    if "supersedes_id" not in have:
        op.create_index("ix_product_supersedes", "product", ["supersedes_id"])


def downgrade() -> None:
    have = _present()
    if "supersedes_id" in have:
        op.drop_index("ix_product_supersedes", table_name="product")
    with op.batch_alter_table("product") as batch:
        for name in COLUMNS:
            if name in have:
                batch.drop_column(name)
