"""Tape-measure readings alongside the weight series (R76).

Circumferences show fat loss with muscle kept, which the scale cannot distinguish. Every
column is optional because people measure what they measure.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "body_measurement"
CM_COLUMNS = ("waist_cm", "belly_cm", "hip_cm", "chest_cm", "neck_cm", "thigh_cm", "arm_cm")


def _exists() -> bool:
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _exists():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(32), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        *(sa.Column(name, sa.Float(), nullable=True) for name in CM_COLUMNS),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "measured_at"),
        sa.CheckConstraint("source IN ('manual','import')", name="ck_body_source"),
    )
    op.create_index("ix_body_measurement_tenant_id", TABLE, ["tenant_id"])


def downgrade() -> None:
    if not _exists():
        return
    op.drop_index("ix_body_measurement_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
