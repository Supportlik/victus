"""Report snapshots (``report_snapshot``): frozen report results plus an assessment.

Revision 0001 builds the schema from the mapped models, so a fresh database
already has the table; the step checks before creating.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "report_snapshot"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(TABLE)


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("report_name", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200)),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("today", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="frozen"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("assessment_md", sa.Text()),
        sa.Column("assessed_at", sa.DateTime(timezone=True)),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("run_id", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(16)),
        sa.CheckConstraint(
            "status IN ('frozen','assessed','failed')", name="ck_report_snapshot_status"
        ),
    )
    op.create_index("ix_report_snapshot_tenant_created", TABLE, ["tenant_id", "created_at"])
    op.create_index("ix_report_snapshot_tenant_status", TABLE, ["tenant_id", "status"])


def downgrade() -> None:
    if not _has_table():
        return
    op.drop_index("ix_report_snapshot_tenant_status", table_name=TABLE)
    op.drop_index("ix_report_snapshot_tenant_created", table_name=TABLE)
    op.drop_table(TABLE)
