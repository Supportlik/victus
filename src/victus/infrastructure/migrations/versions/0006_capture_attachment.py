"""Several files per capture (``capture_attachment``).

Photos and a voice note taken together belong to one note; the link table keeps
their order. ``capture.attachment_id`` still points at the first file.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "capture_attachment"


def _has_table() -> bool:
    return sa.inspect(op.get_bind()).has_table(TABLE)


def upgrade() -> None:
    if not _has_table():
        op.create_table(
            TABLE,
            sa.Column(
                "capture_id",
                sa.String(32),
                sa.ForeignKey("capture.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "attachment_id",
                sa.String(32),
                sa.ForeignKey("attachment.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("ix_capture_attachment_capture", TABLE, ["capture_id", "position"])
    # existing captures keep their single file, now also as a link
    op.execute(
        sa.text(
            f"INSERT INTO {TABLE} (capture_id, attachment_id, position) "
            "SELECT id, attachment_id, 1 FROM capture WHERE attachment_id IS NOT NULL "
            f"AND id NOT IN (SELECT capture_id FROM {TABLE})"
        )
    )


def downgrade() -> None:
    if _has_table():
        op.drop_index("ix_capture_attachment_capture", table_name=TABLE)
        op.drop_table(TABLE)
