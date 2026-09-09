"""Allow the ``assess`` run mode (R72).

An assessment judges a frozen report rather than drafting a day. It is a run like any
other, so it needs the mode column to accept it; the check constraint has to be rewritten
because SQLite cannot alter one in place.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_agent_run_mode"
WITH_ASSESS = "mode IN ('historical','batch','manual','follow_up','assess')"
WITHOUT = "mode IN ('historical','batch','manual','follow_up')"


def _has(condition: str) -> bool:
    """Whether the table's own definition already carries this condition.

    Alembic cannot inspect a check constraint's text on SQLite, so the table SQL is read
    directly; on PostgreSQL the catalogue answers the same question.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        sql = bind.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_run'"
        ).scalar()
        return bool(sql) and condition.replace(" ", "") in str(sql).replace(" ", "")
    found = bind.exec_driver_sql(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %(name)s",
        {"name": NAME},
    ).scalar()
    return bool(found) and condition.replace(" ", "") in str(found).replace(" ", "")


def _rewrite(to: str) -> None:
    with op.batch_alter_table("agent_run") as batch:
        batch.drop_constraint(NAME, type_="check")
        batch.create_check_constraint(NAME, sa.text(to))


def upgrade() -> None:
    if not _has(WITH_ASSESS):
        _rewrite(WITH_ASSESS)


def downgrade() -> None:
    if _has(WITH_ASSESS):
        # runs recorded in the new mode would violate the old constraint
        op.execute(sa.text("DELETE FROM agent_run WHERE mode = 'assess'"))
        _rewrite(WITHOUT)
