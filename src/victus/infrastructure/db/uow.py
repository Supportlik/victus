"""SQLAlchemy Unit of Work: one session, one transaction, tenant-scoped repositories."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from victus.application.tenant_context import TenantContext
from victus.infrastructure.db.repositories import (
    AgentRepo,
    AuditRepo,
    BackupJobRepo,
    BodyMeasurementRepo,
    CaptureRepo,
    DayLogRepo,
    DayMessageRepo,
    ProductRepo,
    ProposalRepo,
    RecipeRepo,
    SettingsRepo,
    SnapshotRepo,
    TargetBandRepo,
    TenantRepo,
    UserRepo,
    WeightRepo,
)


class SqlAlchemyUnitOfWork:
    """Usage::

        with SqlAlchemyUnitOfWork(session_factory, ctx) as uow:
            uow.products.add(...)
            uow.commit()

    Leaving the block without ``commit()`` rolls back.
    """

    def __init__(self, session_factory: sessionmaker[Session], ctx: TenantContext) -> None:
        self._factory = session_factory
        self.ctx = ctx
        self.session: Session

    def __enter__(self) -> Self:
        self.session = self._factory()
        s, c = self.session, self.ctx
        self.tenants = TenantRepo(s, c)
        self.users = UserRepo(s, c)
        self.products = ProductRepo(s, c)
        self.recipes = RecipeRepo(s, c)
        self.day_logs = DayLogRepo(s, c)
        self.weights = WeightRepo(s, c)
        self.body = BodyMeasurementRepo(s, c)
        self.target_bands = TargetBandRepo(s, c)
        self.settings = SettingsRepo(s, c)
        self.captures = CaptureRepo(s, c)
        self.agent = AgentRepo(s, c)
        self.day_messages = DayMessageRepo(s, c)
        self.proposals = ProposalRepo(s, c)
        self.snapshots = SnapshotRepo(s, c)
        self.audit = AuditRepo(s, c)
        self.backup_jobs = BackupJobRepo(s, c)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                self.session.rollback()
            else:
                # Anything not committed is discarded on purpose.
                self.session.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def flush(self) -> None:
        self.session.flush()
