"""Programmatic Alembic entry points used by the CLI, ``serve --migrate`` and tests."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from victus.infrastructure.db.engine import make_engine

HERE = Path(__file__).resolve().parent


def make_config(url: str | None = None, engine: Engine | None = None) -> Config:
    cfg = Config(str(HERE / "alembic.ini"))
    cfg.set_main_option("script_location", str(HERE))
    cfg.attributes["skip_logging"] = True
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    if engine is not None:
        cfg.attributes["engine"] = engine
    return cfg


def upgrade(
    url: str | None = None, revision: str = "head", *, engine: Engine | None = None
) -> None:
    """Migrate the database at ``url`` (or bound to ``engine``) to ``revision``."""
    if engine is None and url is None:
        raise ValueError("either url or engine is required")
    command.upgrade(make_config(url, engine), revision)


def downgrade(
    url: str | None = None, revision: str = "base", *, engine: Engine | None = None
) -> None:
    command.downgrade(make_config(url, engine), revision)


def current(url: str | None = None, *, engine: Engine | None = None) -> str | None:
    """Return the current revision of the database, or ``None`` if unmigrated."""
    eng = engine or make_engine(url or "")
    with eng.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head() -> str:
    return ScriptDirectory.from_config(make_config()).get_current_head() or ""


def is_up_to_date(url: str | None = None, *, engine: Engine | None = None) -> bool:
    return current(url, engine=engine) == head()
