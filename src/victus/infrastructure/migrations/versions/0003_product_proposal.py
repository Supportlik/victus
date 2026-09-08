"""Product change proposals (``product_proposal``).

Revision 0001 builds the schema from the mapped models, so a fresh database
already has the table; the step checks before creating.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "product_proposal"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("product.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capture_id", sa.String(32), sa.ForeignKey("capture.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.String(32)),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("source", sa.String(300)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.String(32)),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_product_proposal_status"
        ),
    )
    op.create_index("ix_product_proposal_tenant_status", TABLE, ["tenant_id", "status"])
    op.create_index("ix_product_proposal_product", TABLE, ["product_id"])


def downgrade() -> None:
    if not _has_table():
        return
    op.drop_index("ix_product_proposal_product", table_name=TABLE)
    op.drop_index("ix_product_proposal_tenant_status", table_name=TABLE)
    op.drop_table(TABLE)
