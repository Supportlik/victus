"""A pending proposal can be corrected before it is decided (R81, R84).

Two nullable columns on ``product_proposal``:

- ``created_by`` names who filed the proposal — the token, the user, or ``system`` for the
  in-house worker — so an actor without ``approve`` may amend its own pending proposal
  and nobody else's.
- ``proposed_changes`` keeps the values as the actor proposed them, written the first time
  a person changes one. The proposal's ``changes`` then hold what will be applied, and the
  history can show the agent's reading beside the person's correction.

Rows filed before this revision carry neither: they have no author an actor could match,
so only a person amends them, and their original values are what ``changes`` holds.

Revision 0001 builds the schema from the mapped models, so a database created after this
revision was written already has both columns; each step reads what is there first.
``ADD COLUMN`` of a nullable column needs no table rebuild on SQLite, which keeps the two
CHECK constraints that revision 0012 had to spell out out of harm's way.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "product_proposal"
COLUMNS: tuple[tuple[str, Any], ...] = (
    ("created_by", sa.String(32)),
    ("proposed_changes", sa.JSON()),
)


def _existing() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    present = _existing()
    for name, type_ in COLUMNS:
        if name not in present:
            op.add_column(TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    # Plain ``DROP COLUMN``, which SQLite has had since 3.35: a batch would rebuild the
    # table from reflection and could lose the CHECKs revision 0012 had to spell out.
    present = _existing()
    for name, _ in reversed(COLUMNS):
        if name in present:
            op.drop_column(TABLE, name)
