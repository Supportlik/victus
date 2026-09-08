"""SQLAlchemy repositories. Every repository is built with a ``TenantContext``
and filters on ``tenant_id`` automatically (directly or via the parent row)."""

from victus.infrastructure.db.repositories.catalog import ProductRepo, RecipeRepo
from victus.infrastructure.db.repositories.diary import (
    DayLogRepo,
    SettingsRepo,
    TargetBandRepo,
    WeightRepo,
)
from victus.infrastructure.db.repositories.inbox import AgentRepo, CaptureRepo, DayMessageRepo
from victus.infrastructure.db.repositories.ops import AuditRepo, BackupJobRepo
from victus.infrastructure.db.repositories.proposals import ProposalRepo
from victus.infrastructure.db.repositories.tenancy import TenantRepo, UserRepo

__all__ = [
    "AgentRepo",
    "AuditRepo",
    "BackupJobRepo",
    "CaptureRepo",
    "DayLogRepo",
    "DayMessageRepo",
    "ProductRepo",
    "ProposalRepo",
    "RecipeRepo",
    "SettingsRepo",
    "TargetBandRepo",
    "TenantRepo",
    "UserRepo",
    "WeightRepo",
]
