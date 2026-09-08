"""Product-linked captures: ``capture.product_id``.

Revision 0001 builds the schema from the mapped models, so a fresh database
already has this column; the step therefore checks before adding.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if _has_column("capture", "product_id"):
        return
    with op.batch_alter_table("capture") as batch:
        batch.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_capture_product", "product", ["product_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_capture_product", ["product_id"])


def downgrade() -> None:
    if not _has_column("capture", "product_id"):
        return
    inspector = sa.inspect(op.get_bind())
    index_names = {ix["name"] for ix in inspector.get_indexes("capture")}
    with op.batch_alter_table("capture") as batch:
        if "ix_capture_product" in index_names:
            batch.drop_index("ix_capture_product")
        # Dropping the column removes its foreign key as well (the constraint is
        # unnamed on databases created from the models at revision 0001).
        batch.drop_column("product_id")
