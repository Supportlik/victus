"""initial schema, views and unit seed

Revision ID: 0001
Revises:
Create Date: 2026-09-08

The first revision creates the schema from the mapped models
(``Base.metadata.create_all``) instead of spelling out ~30 ``op.create_table``
calls: at revision 0001 models and schema are by definition identical, and the
dialect-specific details (partial unique index, CHECK constraints) are already
expressed once on the models. Later revisions use ``op.*`` (autogenerate with
``render_as_batch`` for SQLite).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from victus.infrastructure.db import views
from victus.infrastructure.db.orm import Base
from victus.infrastructure.migrations.units_seed import UNITS

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    views.create_views(bind)
    unit = sa.table(
        "unit",
        sa.column("code", sa.String),
        sa.column("singular", sa.String),
        sa.column("plural", sa.String),
        sa.column("unit_type", sa.String),
        sa.column("factor_base", sa.Float),
        sa.column("needs_portion", sa.Integer),
        sa.column("fuzzy", sa.Integer),
    )
    op.bulk_insert(
        unit,
        [
            {
                "code": code,
                "singular": singular,
                "plural": plural,
                "unit_type": unit_type,
                "factor_base": factor,
                "needs_portion": needs_portion,
                "fuzzy": fuzzy,
            }
            for code, singular, plural, unit_type, factor, needs_portion, fuzzy in UNITS
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()
    views.drop_views(bind)
    Base.metadata.drop_all(bind)
