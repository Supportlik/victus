"""T-API-110: each documented scope profile, minted as a token, can and cannot call what
``docs/API.md`` says — the REST routes, checked over HTTP, and the MCP tools by declaration
(the MCP side over HTTP is T-MCP-102).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from tests.integration.api.profile_doc import documented_profiles
from victus.api.scopes import ROUTE_SCOPES
from victus.application.scope_profiles import PROFILES, WORKER, ScopeProfile
from victus.application.tenant_context import SCOPE_APPROVE
from victus.application.use_cases._base import UowFactory
from victus.mcp.tools import WORKER_TOOLS, get_tool

pytestmark = pytest.mark.api


def _profile_ids(p: ScopeProfile) -> str:
    return p.key


def test_t_api_110_every_profile_is_documented_with_its_scopes() -> None:
    """T-API-110: API.md documents exactly the code's profiles, with the same scope lists."""
    docs = documented_profiles()
    assert set(docs) == {p.title for p in PROFILES}
    for profile in PROFILES:
        doc = docs[profile.title]
        assert doc.scopes == profile.scope_list, profile.title
        if profile is not WORKER:
            assert f"--scopes {profile.scope_list} " in doc.command + " ", doc.command
        for kind in ("can", "fallback", "refused"):
            assert kind in doc.lists, f"{profile.title}: no '{kind}' list"
        named = [*doc.lists["can"], *doc.lists["fallback"], *doc.lists["refused"]]
        assert named, profile.title


@pytest.mark.parametrize("profile", PROFILES, ids=_profile_ids)
def test_t_api_110_documented_tools_match_the_declarations(profile: ScopeProfile) -> None:
    """T-API-110: every MCP tool a profile names is allowed, a fallback, or refused as written."""
    doc = documented_profiles()[profile.title]
    scopes = frozenset(profile.scopes)

    def handed(name: str) -> bool:
        spec = get_tool(name)
        ok = spec.scope.allows_scopes(scopes)
        return ok and (profile is not WORKER or name in WORKER_TOOLS)

    for name in doc.tools("can"):
        assert handed(name), f"{profile.title} should be able to call {name}"
        assert get_tool(name).without_approve is None or SCOPE_APPROVE in scopes, name
    for name in doc.tools("fallback"):
        assert handed(name), f"{profile.title} should reach {name}"
        assert get_tool(name).without_approve and SCOPE_APPROVE not in scopes, name
    for name in doc.tools("refused"):
        assert not handed(name), f"{profile.title} must not call {name}"


@pytest.mark.parametrize("profile", [p for p in PROFILES if p is not WORKER], ids=_profile_ids)
def test_t_api_110_documented_routes_answer_as_written(
    profile: ScopeProfile,
    api_app: FastAPI,
    alice_account: Account,
    api_factory: UowFactory,
) -> None:
    """T-API-110: minted as a real token, a profile is let through or refused on each route."""
    doc = documented_profiles()[profile.title]
    headers = bearer(api_factory, alice_account, list(profile.scopes))
    client = TestClient(api_app)
    for kind in ("can", "fallback", "refused"):
        for key in doc.routes(kind):
            declared = ROUTE_SCOPES.get(key)
            assert declared is not None, f"{key} is not a route"
            if kind == "refused":
                # token management declares no scope: its use cases refuse a token without admin
                unscoped = not declared.requires.groups
                assert unscoped or not declared.requires.allows_scopes(frozenset(profile.scopes)), (
                    key
                )
            else:
                assert declared.requires.allows_scopes(frozenset(profile.scopes)), key
                fallback = declared.without_approve is not None
                assert fallback == (kind == "fallback" and SCOPE_APPROVE not in profile.scopes), key
            method, path = key.split(" ", 1)
            if key == "GET /events" and kind != "refused":
                continue  # an accepted stream never ends; T-API-076…081 read it properly
            # a body-less request with placeholder ids: the scope check runs before anything else
            url = "/api/v1" + path.replace("{day}", "2026-03-10").replace("{name}", "checkup")
            for placeholder in ("{product_id}", "{portion_id}", "{meal_id}", "{proposal_id}"):
                url = url.replace(placeholder, "999999")
            url = (
                url.replace("{capture_id}", "cap_missing")
                .replace("{attachment_id}", "att_missing")
                .replace("{token_id}", "tok_missing")
            )
            r = client.request(method, url, headers=headers)
            if kind == "refused":
                assert r.status_code == 403, f"{profile.title}: {key} answered {r.status_code}"
            else:
                assert r.status_code not in (401, 403), f"{profile.title}: {key} {r.text}"
