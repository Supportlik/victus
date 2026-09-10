"""A transcript belongs to a recording, not to the capture (R65).

Two spoken notes in one capture is an ordinary thing to do, and ``transcript`` had room
for exactly one row per capture, so the second note was stored, played and never read.
``attachment_id`` says which recording a transcript came from; it stays nullable because
the rows written before it existed cannot be re-derived where a capture holds no audio.

Existing rows are attributed to the capture's first recording, which is the only part
that was ever sent to a provider.

Revision 0001 builds the schema from the mapped models, so a fresh database already has
the column and its foreign key; every step below checks before it creates.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "transcript"
COLUMN = "attachment_id"
FK = "fk_transcript_attachment"

#: Attribute each row that has no recording yet to the capture's first audio part, in the
#: order the files were added. Rows whose capture has no audio left stay null.
_BACKFILL = sa.text(
    f"UPDATE {TABLE} SET {COLUMN} = ("
    "  SELECT ca.attachment_id FROM capture_attachment ca"
    "    JOIN attachment a ON a.id = ca.attachment_id"
    "   WHERE ca.capture_id = transcript.capture_id"
    "     AND (a.mime LIKE 'audio/%' OR a.mime LIKE 'video/%')"
    "   ORDER BY ca.position LIMIT 1"
    f") WHERE {COLUMN} IS NULL"
)


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _attachment_fks() -> set[str]:
    """Names of the foreign keys already covering ``attachment_id``, however named.

    A database built by revision 0001 carries the mapped model's key under the name the
    dialect chose, not under ``FK``; matching on the column is what tells them apart.
    """
    return {
        name
        for c in sa.inspect(op.get_bind()).get_foreign_keys(TABLE)
        if c["constrained_columns"] == [COLUMN] and (name := c["name"]) is not None
    }


def upgrade() -> None:
    if COLUMN not in _columns():
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column(COLUMN, sa.String(32), nullable=True))
    # SQLite cannot ALTER a constraint into place, so an existing SQLite file keeps the
    # column without the key; PostgreSQL gets it explicitly, unless 0001 already did.
    if op.get_bind().dialect.name == "postgresql" and not _attachment_fks():
        op.create_foreign_key(FK, TABLE, "attachment", [COLUMN], ["id"], ondelete="SET NULL")
    op.execute(_BACKFILL)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for name in _attachment_fks():
            op.drop_constraint(name, TABLE, type_="foreignkey")
    if COLUMN in _columns():
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
