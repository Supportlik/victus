"""Database plumbing for CLI commands (engine and unit-of-work factory from config)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import TenantContext
from victus.application.use_cases._base import UowFactory
from victus.config.server import ServerConfig, load_server_config
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork


def uow_factory_from_config(
    config: ServerConfig | None = None,
) -> tuple[UowFactory, sessionmaker[Session]]:
    cfg = config or load_server_config()
    engine = make_engine(cfg.database.url, echo=cfg.database.echo)
    session_factory = make_session_factory(engine)

    def make(ctx: TenantContext) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, ctx)

    return make, session_factory
