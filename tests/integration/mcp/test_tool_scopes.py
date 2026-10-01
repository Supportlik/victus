"""T-MCP-100…102: every MCP tool declares the scopes its use case enforces.

Each :class:`~victus.mcp.tools.ToolSpec` carries a :class:`Requires`. For every tool the
smallest scope sets it names succeed through :func:`dispatch`, and each set with one scope
taken away is refused — by ``dispatch`` before the handler runs, and by the use case when
the handler is called directly. A declaration that is wider or narrower than the use case
fails here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.integration.api.scope_env import PNG, Env
from victus.api.app import create_app
from victus.application.errors import ApplicationError
from victus.application.tenant_context import (
    ALL_SCOPES,
    SCOPE_ADMIN,
    ScopeError,
    TenantContext,
)
from victus.config.server import ServerConfig
from victus.infrastructure.migrations import runner
from victus.infrastructure.storage.fs_blob import FsBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription
from victus.mcp.server import make_tool_context
from victus.mcp.tools import TOOLS, ToolContext, ToolError, dispatch, get_tool


@dataclass
class Call:
    args: dict[str, Any]
    run_id: str | None = None
    #: Tool error codes that still mean "the scopes were enough".
    also_ok: tuple[str, ...] = field(default_factory=tuple)


class ToolEnv:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.config: ServerConfig = env.app.state.config
        self.blobs = FsBlobStorage(self.config.storage.path)

    def tc(self, scopes: frozenset[str], run_id: str | None = None) -> ToolContext:
        ctx = TenantContext(
            tenant_id=self.env.tenant_id, token_id="tok_scope_test", scopes=frozenset(scopes)
        )
        tc = make_tool_context(
            self.env.app.state.session_factory,
            ctx,
            self.config,
            blobs=self.blobs,
            transcription=FakeTranscription("one apple"),
        )
        return dataclasses.replace(tc, run_id=run_id)

    def owner(self, name: str, args: dict[str, Any], run_id: str | None = None) -> Any:
        return dispatch(self.tc(ALL_SCOPES, run_id), name, args)

    def run(self, day: str | None = None) -> tuple[str, str]:
        day = day or self.env.fresh_date()
        run = self.owner("agent_run_start", {"mode": "manual", "dates": [day]})
        assert run["locked_days"] == [day], run
        return day, str(run["run_id"])

    def audio(self) -> str:
        cap = self.env.call(
            "POST",
            "/captures",
            files={"file": ("note.oga", b"OggS-fake", "application/octet-stream")},
        )
        return str(cap["id"])


Builder = Callable[[ToolEnv], Call]


def _draft(t: ToolEnv) -> Call:
    day, run_id = t.run()
    item = {
        "raw_text": "a tub of skyr",
        "candidates": [],
        "chosen_consumable_id": t.env.ids["product"],
        "quantity": 150,
        "unit_code": "g",
        "estimated": False,
        "quantity_estimated": False,
        "confidence": 0.9,
        "rationale": "Named in the note.",
        "source_kind": "text",
        "source_capture_id": "cap_test",
    }
    return Call(
        {
            "run_id": run_id,
            "date": day,
            "source_captures": [],
            "training": "rest",
            "meals": [{"name": "Breakfast", "time": "08:30", "line_items": [item]}],
        },
        run_id=run_id,
    )


def _message(t: ToolEnv) -> Call:
    day, run_id = t.run()
    return Call({"run_id": run_id, "date": day, "kind": "note", "content": "ok"}, run_id=run_id)


def _finish(t: ToolEnv) -> Call:
    _, run_id = t.run()
    return Call({"run_id": run_id, "status": "finished"}, run_id=run_id)


def _draft_day(t: ToolEnv) -> str:
    return t.env.draft_item()[0]


def _id(name: str) -> Builder:
    return lambda t: Call({name: t.env.ids[{"id": "product"}.get(name, name)]})


TOOL_CALLS: dict[str, Builder] = {
    "agent_message_add": _message,
    "agent_run_finish": _finish,
    "agent_run_start": lambda t: Call({"mode": "manual", "dates": [t.env.fresh_date()]}),
    "body_add": lambda t: Call({"measured_at": t.env.stamp(), "waist_cm": 80}),
    "body_measurements": lambda t: Call({}),
    "capture_get": lambda t: Call({"id": t.audio()}),
    "capture_mark": lambda t: Call({"id": t.env.capture()["id"], "status": "processed"}),
    "captures_open": lambda t: Call({"scope": "all"}),
    "day_approve": lambda t: Call({"date": _draft_day(t), "close": True}),
    "day_get": lambda t: Call({"date": t.env.ids["day"]}),
    "day_message_add": lambda t: Call({"date": t.env.day(), "text": "it was 150 g"}),
    "day_thread_get": lambda t: Call({"date": t.env.ids["day"]}),
    "days_list": lambda t: Call({"from": "2025-01-01", "to": "2025-12-31"}),
    "draft_create": _draft,
    "draft_discard": lambda t: Call({"date": _draft_day(t)}),
    "draft_summary": lambda t: Call({"date": _draft_day(t)}),
    "drafts_list": lambda t: Call({}),
    "line_item_approve": lambda t: Call({"line_item_id": t.env.draft_item()[1]}),
    "line_item_create": lambda t: Call(
        {
            "date": t.env.day(),
            "meal": "Lunch",
            "consumable_id": t.env.ids["product"],
            "amount": 100,
            "unit_code": "g",
        }
    ),
    "line_item_delete": lambda t: Call({"line_item_id": t.env.draft_item()[1]}),
    "line_item_update": lambda t: Call({"line_item_id": t.env.draft_item()[1], "amount": 120}),
    "meal_delete": lambda t: Call({"meal_id": t.env.meal()[1]}),
    "meal_update": lambda t: Call({"meal_id": t.env.meal()[1], "name": "Brunch"}),
    "portion_create": lambda t: Call(
        {"product_id": t.env.product()["id"], "unit_code": "slice", "label": "slice", "amount": 30}
    ),
    "portion_delete": lambda t: Call(
        {"portion_id": t.env.portion(t.env.ids["product"])["id"], "reason": "duplicate row"}
    ),
    "portion_update": lambda t: Call(
        {"portion_id": t.env.portion(t.env.ids["product"])["id"], "amount": 55}
    ),
    "product_create": lambda t: Call({"name": f"Oat drink {t.env.fresh_date()}", "kcal": 45}),
    "product_get": _id("id"),
    "product_propose": lambda t: Call(
        {"product_id": t.env.product()["id"], "changes": {"kcal": 70}, "source": "label"}
    ),
    "proposal_update": lambda t: Call(
        {"proposal_id": _own_proposal(t), "changes": {"kcal": 71}, "rationale": "misread"}
    ),
    "product_search": lambda t: Call({"q": "skyr"}),
    "product_update": lambda t: Call({"product_id": t.env.product()["id"], "kcal": 64}),
    "product_usage": lambda t: Call({"product_id": t.env.ids["product"]}),
    "product_version_create": lambda t: Call(
        {"id": t.env.product()["id"], "valid_from": "2026-06-01", "changes": {"kcal": 70}}
    ),
    "product_versions": _id("id"),
    "recipe_get": lambda t: Call({"id": t.env.ids["recipe"]}),
    "report_assess": lambda t: Call({"snapshot_id": t.env.snapshot(), "assessment_md": "Fine."}),
    "report_render": lambda t: Call({"name": "checkup"}),
    "report_snapshot_create": lambda t: Call({"name": "checkup"}),
    "report_snapshot_get": lambda t: Call({"snapshot_id": t.env.ids["snapshot"]}),
    "report_snapshots_list": lambda t: Call({}),
    "rule_delete": lambda t: Call({"name": _rule(t)}),
    "rule_upsert": lambda t: Call({"when": "rolls", "then": "two"}),
    "rules_list": lambda t: Call({}),
    "weight_add": lambda t: Call({"measured_at": t.env.stamp(), "kg": 80.4}),
}


def _own_proposal(t: ToolEnv) -> str:
    """A pending proposal filed by the same token the scope test calls with."""
    filed = t.owner(
        "product_propose",
        {"product_id": t.env.product()["id"], "changes": {"kcal": 70}, "source": "label"},
    )
    return str(filed["id"])


def _rule(t: ToolEnv) -> str:
    name = f"rule-{t.env.fresh_date()}"
    t.env.call("PUT", "/settings/rules", json={"when": "bread", "then": "one", "name": name})
    return name


def _accepted() -> list[tuple[str, frozenset[str]]]:
    return [(t.name, s) for t in TOOLS for s in t.scope.minimal_sets()]


def _refused() -> list[tuple[str, frozenset[str]]]:
    cases: set[tuple[str, frozenset[str]]] = set()
    for spec in TOOLS:
        filler = sorted(ALL_SCOPES - spec.scope.scopes - {SCOPE_ADMIN})
        for minimal in spec.scope.minimal_sets():
            for scope in minimal:
                held = (minimal - {scope}) or frozenset(filler[:1])
                if not spec.scope.allows_scopes(held):
                    cases.add((spec.name, held))
    return sorted(cases, key=lambda c: (c[0], sorted(c[1])))


def _name(case: tuple[str, frozenset[str]]) -> str:
    return f"{case[0]} [{','.join(sorted(case[1]))}]"


@pytest.fixture(scope="module")
def tools_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ToolEnv]:
    tmp = tmp_path_factory.mktemp("tool-scopes")
    config = ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": f"sqlite:///{(tmp / 'tools.db').as_posix()}"},
        storage={"path": str(tmp / "blobs")},
        auth={"rp_id": "localhost", "origin": "http://localhost"},
        mcp={"rate_limit_per_minute": 100_000},
    )
    app = create_app(config)
    runner.upgrade(engine=app.state.engine)
    env = Env(app)
    assert env.capture(files={"file": ("x.png", PNG, "image/png")})
    yield ToolEnv(env)
    app.state.engine.dispose()


def test_t_mcp_100_every_tool_has_a_call() -> None:
    """T-MCP-100: the catalogue of valid calls covers the whole registry."""
    assert set(TOOL_CALLS) == {t.name for t in TOOLS}
    for spec in TOOLS:
        assert spec.scope.groups, f"{spec.name} declares no scope"


@pytest.mark.parametrize("case", _accepted(), ids=_name)
def test_t_mcp_100_minimal_scopes_are_enough(
    tools_env: ToolEnv, case: tuple[str, frozenset[str]]
) -> None:
    """T-MCP-100: each smallest scope set a tool declares gets through dispatch and use case."""
    name, scopes = case
    call = TOOL_CALLS[name](tools_env)
    try:
        dispatch(tools_env.tc(scopes, call.run_id), name, call.args)
    except ToolError as exc:
        assert exc.code in call.also_ok, f"{name} with {sorted(scopes)}: {exc.code} {exc.message}"


@pytest.mark.parametrize("case", _refused(), ids=_name)
def test_t_mcp_101_dispatch_refuses_a_missing_scope(
    tools_env: ToolEnv, case: tuple[str, frozenset[str]]
) -> None:
    """T-MCP-101: one scope short of the declaration is `forbidden` before the handler runs."""
    name, scopes = case
    call = TOOL_CALLS[name](tools_env)
    with pytest.raises(ToolError) as refused:
        dispatch(tools_env.tc(scopes, call.run_id), name, call.args)
    assert refused.value.code == "forbidden" and "required" in refused.value.message


@pytest.mark.parametrize("case", _refused(), ids=_name)
def test_t_mcp_101_use_case_refuses_a_missing_scope(
    tools_env: ToolEnv, case: tuple[str, frozenset[str]]
) -> None:
    """T-MCP-101: called past the dispatch check, the use case behind the tool refuses too."""
    name, scopes = case
    spec = get_tool(name)
    call = TOOL_CALLS[name](tools_env)
    inp = spec.input_model.model_validate(call.args)
    with pytest.raises((ScopeError, ToolError)) as refused:
        spec.handler(tools_env.tc(scopes, call.run_id), inp)
    if isinstance(refused.value, ToolError):
        assert refused.value.code == "forbidden"
    assert not isinstance(refused.value, ApplicationError)
