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


# ── scope requirements: one declaration per tool and route ──────────────────


@dataclass(frozen=True, slots=True)
class Requires:
    """The scopes an action needs: every group must hold, one scope of a group suffices.

    ``Requires.of("read", ("agent:write", "write"))`` reads "``read`` and either
    ``agent:write`` or ``write``". An empty requirement means any authenticated principal.
    MCP tools and REST routes declare one of these; the scope-consistency tests check the
    declaration against what the use case behind it actually enforces.
    """

    groups: tuple[frozenset[str], ...] = ()

    @classmethod
    def of(cls, *items: str | tuple[str, ...]) -> Requires:
        groups: list[frozenset[str]] = []
        for item in items:
            group = frozenset({item}) if isinstance(item, str) else frozenset(item)
            unknown = group - ALL_SCOPES
            if unknown or not group:
                raise ValueError(f"unknown scopes in requirement: {sorted(unknown)}")
            groups.append(group)
        return cls(tuple(groups))

    def allows(self, ctx: TenantContext) -> bool:
        return all(any(ctx.has_scope(s) for s in group) for group in self.groups)

    def allows_scopes(self, scopes: frozenset[str] | set[str]) -> bool:
        return self.allows(TenantContext(tenant_id="-", scopes=frozenset(scopes)))

    def check(self, ctx: TenantContext) -> None:
        """Raise :class:`ScopeError` naming the first group the context does not satisfy."""
        for group in self.groups:
            if not any(ctx.has_scope(s) for s in group):
                raise ScopeError(f"scope {_group_label(group, quote=True)} required")

    def minimal_sets(self) -> list[frozenset[str]]:
        """Every smallest scope set that satisfies the requirement (one pick per group)."""
        sets: list[frozenset[str]] = [frozenset()]
        for group in self.groups:
            sets = [s | {pick} for s in sets for pick in sorted(group)]
        unique = set(sets)
        minimal = [s for s in unique if not any(o < s for o in unique)]
        return sorted(minimal, key=sorted)

    @property
    def scopes(self) -> frozenset[str]:
        out: frozenset[str] = frozenset()
        for group in self.groups:
            out |= group
        return out

    def label(self) -> str:
        if not self.groups:
            return "—"
        return " + ".join(_group_label(g) for g in self.groups)


def _group_label(group: frozenset[str], *, quote: bool = False) -> str:
    names = [f"'{s}'" if quote else s for s in sorted(group)]
    if len(names) == 1:
        return names[0]
    joined = " or ".join(names)
    return joined if quote else f"({joined})"


#: A person's session carries the scopes of their role; only an owner administers.
ROLE_SCOPES: dict[str, frozenset[str]] = {
    "owner": ALL_SCOPES,
    "member": ALL_SCOPES - {SCOPE_ADMIN},
}


def scopes_for_role(role: str | None) -> frozenset[str]:
    """The scopes of a role; an unknown role gets none rather than a guess."""
    return ROLE_SCOPES.get(role or "", frozenset())
