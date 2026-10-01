"""The scopes every REST route needs, declared once.

``current_principal`` checks the matched route against this table before the route
runs, so a token without the scopes gets ``403`` — even before its body is validated.
The use cases check the same scopes again (defence in depth, and the CLI has no routes);
``tests/integration/api/test_route_scopes.py`` holds the two together for every route,
and ``docs/SCOPES.md`` is generated from this table and the MCP registry.

A route that is not listed here is not checked here — the test that every route is
listed is what keeps that from happening unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass

from victus.application.tenant_context import (
    SCOPE_ADMIN,
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
    Requires,
)

_APPLY_OR_PROPOSE = "applied with write + approve; otherwise filed as a proposal (202)"


@dataclass(frozen=True, slots=True)
class RouteScope:
    requires: Requires
    #: What more some calls need, or who else may call it.
    note: str | None = None
    #: No principal at all is needed (login, health).
    public: bool = False
    #: What a call without ``approve`` turns into instead of a fact (ADR 0013).
    without_approve: str | None = None


def _r(
    *items: str | tuple[str, ...], note: str | None = None, without_approve: str | None = None
) -> RouteScope:
    if without_approve is None and note == _APPLY_OR_PROPOSE:
        without_approve = "proposal"
    return RouteScope(Requires.of(*items), note, without_approve=without_approve)


_PUBLIC = RouteScope(Requires(), public=True)
_SIGNED_IN = RouteScope(Requires(), note="a person's session")
_READ = _r(SCOPE_READ)
_WRITE = _r(SCOPE_WRITE)
_DECISION = _r(SCOPE_WRITE, SCOPE_APPROVE)
_PROPOSE = (SCOPE_AGENT_WRITE, SCOPE_WRITE)
_TOKENS = RouteScope(
    Requires(),
    note="a session: own tokens, an owner every token; a token only with admin",
)

ROUTE_SCOPES: dict[str, RouteScope] = {
    # agent
    "GET /agent/status": _READ,
    "POST /agent/runs": _r(SCOPE_AGENT_WRITE),
    "GET /agent/runs": _READ,
    "GET /agent/runs/{run_id}": _READ,
    "POST /agent/runs/{run_id}/cancel": _r(SCOPE_AGENT_WRITE),
    "GET /agent/locks": _READ,
    "DELETE /agent/locks/{day}": _r(SCOPE_AGENT_WRITE),
    # auth
    "POST /auth/webauthn/register/options": _SIGNED_IN,
    "POST /auth/webauthn/register/verify": _SIGNED_IN,
    "POST /auth/webauthn/login/options": _PUBLIC,
    "POST /auth/webauthn/login/verify": _PUBLIC,
    "POST /auth/recovery": _PUBLIC,
    "POST /auth/logout": _PUBLIC,
    "GET /auth/me": _PUBLIC,
    "GET /auth/passkeys": _SIGNED_IN,
    "DELETE /auth/passkeys/{passkey_id}": _SIGNED_IN,
    "GET /auth/tokens": _TOKENS,
    "POST /auth/tokens": RouteScope(
        Requires(),
        note="a session grants only scopes its role holds; a token needs admin",
    ),
    "DELETE /auth/tokens/{token_id}": _TOKENS,
    # captures
    "POST /captures": _r(SCOPE_CAPTURE_WRITE),
    "GET /captures": _r(SCOPE_CAPTURE_READ),
    "DELETE /captures/{capture_id}": _r(SCOPE_CAPTURE_WRITE),
    "GET /captures/{capture_id}": _r(SCOPE_CAPTURE_READ),
    "PATCH /captures/{capture_id}": _r(SCOPE_CAPTURE_WRITE),
    "POST /captures/{capture_id}/transcribe": _r(SCOPE_CAPTURE_WRITE),
    "GET /attachments/{attachment_id}": _r(SCOPE_CAPTURE_READ),
    # days
    "GET /days": _READ,
    "GET /days/{day}": _READ,
    "POST /days/{day}": _WRITE,
    "PUT /days/{day}": _r(SCOPE_WRITE, note="setting reliable needs approve"),
    "POST /days/{day}/meals": _WRITE,
    "PATCH /meals/{meal_id}": _WRITE,
    "DELETE /meals/{meal_id}": _WRITE,
    "POST /meals/{meal_id}/line-items": _r(
        SCOPE_WRITE, note="without approve the item is a draft", without_approve="draft"
    ),
    "PATCH /line-items/{item_id}": _r(SCOPE_WRITE, note="an approved item needs approve"),
    "DELETE /line-items/{item_id}": _r(
        SCOPE_WRITE,
        (SCOPE_AGENT_WRITE, SCOPE_APPROVE),
        note="agent:write withdraws a draft; an approved item needs approve",
    ),
    "POST /days/{day}/close": _DECISION,
    "POST /days/{day}/reopen": _DECISION,
    "GET /days/{day}/messages": _READ,
    "POST /days/{day}/messages": _WRITE,
    # drafts
    "GET /drafts": _READ,
    "GET /drafts/{day}/summary": _READ,
    "POST /drafts/{day}/approve": _DECISION,
    "POST /line-items/{item_id}/approve": _DECISION,
    "POST /drafts/{day}/discard": _DECISION,
    # events
    "GET /events": _r(SCOPE_READ, SCOPE_CAPTURE_READ),
    # master data
    "GET /units": _READ,
    "GET /categories": _READ,
    "POST /categories": _WRITE,
    # products
    "GET /products": _READ,
    "POST /products": _r(_PROPOSE, note=_APPLY_OR_PROPOSE),
    "POST /products/match": _READ,
    "GET /products/{product_id}": _READ,
    "GET /products/{product_id}/versions": _READ,
    "POST /products/{product_id}/versions": _r(_PROPOSE, note=_APPLY_OR_PROPOSE),
    "GET /products/{product_id}/usage": _READ,
    "PATCH /products/{product_id}": _r(_PROPOSE, note=_APPLY_OR_PROPOSE),
    "DELETE /products/{product_id}": _DECISION,
    "GET /products/{product_id}/portions": _READ,
    "POST /products/{product_id}/portions": _r(_PROPOSE, note=_APPLY_OR_PROPOSE),
    "PATCH /portions/{portion_id}": _r(SCOPE_READ, _PROPOSE, note=_APPLY_OR_PROPOSE),
    "DELETE /portions/{portion_id}": _r(SCOPE_READ, _PROPOSE, note=_APPLY_OR_PROPOSE),
    # proposals
    "GET /proposals": _READ,
    "GET /proposals/{proposal_id}": _READ,
    "POST /proposals/{proposal_id}/approve": _DECISION,
    "POST /proposals/{proposal_id}/reject": _DECISION,
    "PATCH /proposals/{proposal_id}": _r(
        (SCOPE_AGENT_WRITE, SCOPE_WRITE),
        (SCOPE_AGENT_WRITE, SCOPE_APPROVE),
        note="a person: write + approve; agent:write amends only its own pending proposal",
    ),
    # recipes
    "GET /recipes": _READ,
    "POST /recipes": _WRITE,
    "GET /recipes/{recipe_id}": _READ,
    "PATCH /recipes/{recipe_id}": _WRITE,
    "PUT /recipes/{recipe_id}/ingredients": _WRITE,
    "POST /recipes/{recipe_id}/batches": _WRITE,
    "GET /batches/{batch_id}": _READ,
    # reports
    "POST /reports/{name}/snapshots": _r(SCOPE_READ, SCOPE_WRITE),
    "GET /reports/snapshots": _READ,
    "GET /reports/snapshots/{snapshot_id}": _READ,
    "POST /reports/snapshots/{snapshot_id}/assess": _r(_PROPOSE),
    "DELETE /reports/snapshots/{snapshot_id}": _WRITE,
    "GET /reports": _READ,
    "POST /reports/{name}/render": _READ,
    "GET /reports/checkup": _READ,
    # settings
    "GET /settings": _READ,
    "PUT /settings": _WRITE,
    "GET /settings/rules": _READ,
    "PUT /settings/rules": _WRITE,
    "DELETE /settings/rules/{name}": _WRITE,
    "GET /settings/versions": _READ,
    "GET /target-bands": _READ,
    "POST /target-bands": _WRITE,
    # system
    "GET /backup/jobs": _r(SCOPE_ADMIN),
    "GET /health": _PUBLIC,
    "GET /version": _PUBLIC,
    # tenant
    "GET /tenant": _r(SCOPE_ADMIN, note="an owner's session holds admin"),
    "GET /tenant/users": _r(SCOPE_ADMIN, note="an owner's session holds admin"),
    "POST /tenant/users": _r(SCOPE_ADMIN, note="an owner's session holds admin"),
    # weight and body
    "GET /weight": _READ,
    "POST /weight": _WRITE,
    "DELETE /weight/{entry_id}": _WRITE,
    "GET /body-measurements": _READ,
    "POST /body-measurements": _WRITE,
    "DELETE /body-measurements/{row_id}": _WRITE,
}


def route_key(method: str, path: str, prefix: str = "/api/v1") -> str:
    """``"GET /days/{day}"`` for a route mounted at ``/api/v1/days/{day}``."""
    if path.startswith(prefix):
        path = path[len(prefix) :] or "/"
    return f"{method.upper()} {path}"


def declared(method: str, path: str) -> RouteScope | None:
    return ROUTE_SCOPES.get(route_key(method, path))
