"""Unit of Work port: one use-case execution = one transaction."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from victus.application.ports.repositories import (
    AgentRepository,
    AuditRepository,
    BackupJobRepository,
    CaptureRepository,
    DayLogRepository,
    DayMessageRepository,
    ProductRepository,
    RecipeRepository,
    SettingsRepository,
    TargetBandRepository,
    TenantRepository,
    UserRepository,
    WeightRepository,
)
from victus.application.tenant_context import TenantContext


class UnitOfWork(Protocol):
    ctx: TenantContext

    @property
    def tenants(self) -> TenantRepository: ...

    @property
    def users(self) -> UserRepository: ...

    @property
    def products(self) -> ProductRepository: ...

    @property
    def recipes(self) -> RecipeRepository: ...

    @property
    def day_logs(self) -> DayLogRepository: ...

    @property
    def weights(self) -> WeightRepository: ...

    @property
    def target_bands(self) -> TargetBandRepository: ...

    @property
    def settings(self) -> SettingsRepository: ...

    @property
    def captures(self) -> CaptureRepository: ...

    @property
    def agent(self) -> AgentRepository: ...

    @property
    def day_messages(self) -> DayMessageRepository: ...

    @property
    def audit(self) -> AuditRepository: ...

    @property
    def backup_jobs(self) -> BackupJobRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def flush(self) -> None: ...
