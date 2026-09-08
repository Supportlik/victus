"""An explicit icon per product (``product.icon``).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == "icon" for c in inspector.get_columns("product"))


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("product") as batch:
        batch.add_column(sa.Column("icon", sa.String(8), nullable=True))


def downgrade() -> None:
    if not _has_column():
        return
    with op.batch_alter_table("product") as batch:
        batch.drop_column("icon")
