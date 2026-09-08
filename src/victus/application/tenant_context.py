"""Who is acting, for which tenant, with which scopes.

Built by the primary adapters (API from session/token, CLI from ``--tenant``,
MCP from its token) and passed into every use case and repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_APPROVE = "approve"
SCOPE_CAPTURE_READ = "capture:read"
SCOPE_CAPTURE_WRITE = "capture:write"
SCOPE_AGENT_WRITE = "agent:write"
SCOPE_ADMIN = "admin"

ALL_SCOPES: frozenset[str] = frozenset(
    {
        SCOPE_READ,
        SCOPE_WRITE,
        SCOPE_APPROVE,
        SCOPE_CAPTURE_READ,
        SCOPE_CAPTURE_WRITE,
        SCOPE_AGENT_WRITE,
        SCOPE_ADMIN,
    }
)


class ScopeError(PermissionError):
    """Raised when an action needs a scope the context does not hold."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    user_id: str | None = None
    token_id: str | None = None
    scopes: frozenset[str] = field(default_factory=lambda: ALL_SCOPES)

    def has_scope(self, scope: str) -> bool:
        return SCOPE_ADMIN in self.scopes or scope in self.scopes

    def require(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise ScopeError(f"scope '{scope}' required")

    @property
    def actor_kind(self) -> str:
        if self.token_id:
            return "token"
        if self.user_id:
            return "user"
        return "system"

    @property
    def actor_id(self) -> str | None:
        return self.token_id or self.user_id
