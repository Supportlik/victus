"""T-OPS-100: ``docs/SCOPES.md`` is what ``scripts/scope_matrix.py`` generates from the code;
T-OPS-101: the web app's scope list and presets are the server's scopes and profiles."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from victus.application.scope_profiles import PROFILES, WORKER
from victus.application.tenant_context import ALL_SCOPES

pytestmark = pytest.mark.domain

ROOT = Path(__file__).resolve().parents[3]
WEB_PROFILES = ROOT / "web" / "src" / "app" / "features" / "settings" / "scope-profiles.ts"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scope_matrix", ROOT / "scripts" / "scope_matrix.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_t_ops_100_scope_matrix_is_current(capsys: pytest.CaptureFixture[str]) -> None:
    """T-OPS-100: the committed matrix equals a fresh rendering; `--check` says so."""
    matrix = _module()
    committed = (ROOT / "docs" / "SCOPES.md").read_text(encoding="utf-8")
    assert committed == matrix.render(), "docs/SCOPES.md is stale: run scripts/scope_matrix.py"
    assert matrix.main(["--check"]) == 0
    assert "is current" in capsys.readouterr().out


def test_t_ops_100_check_fails_on_a_stale_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-OPS-100: a hand edit is reported, and a rewrite puts it right."""
    matrix = _module()
    stale = tmp_path / "docs" / "SCOPES.md"
    stale.parent.mkdir()
    stale.write_text("# Scope matrix\n\nedited by hand\n", encoding="utf-8")
    monkeypatch.setattr(matrix, "ROOT", tmp_path)
    monkeypatch.setattr(matrix, "TARGET", stale)
    assert matrix.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out
    assert matrix.main([]) == 0
    assert stale.read_text(encoding="utf-8") == matrix.render()


def test_t_ops_100_matrix_names_every_tool_route_and_profile() -> None:
    """T-OPS-100: every row and column of the matrix comes from the code."""
    from victus.api.scopes import ROUTE_SCOPES
    from victus.mcp.tools import TOOLS

    text = _module().render()
    for spec in TOOLS:
        assert f"| `{spec.name}` |" in text
    for key in ROUTE_SCOPES:
        assert f"| `{key}` |" in text
    for profile in PROFILES:
        assert profile.title in text and f"`{profile.scope_list}`" in text
    assert "settings" not in re.findall(r"`([a-z:]+)`", text.split("## MCP tools")[0])


def test_t_ops_101_web_presets_are_the_server_profiles() -> None:
    """T-OPS-101: the settings page offers the server's scopes and its token profiles, as-is."""
    ts = WEB_PROFILES.read_text(encoding="utf-8")
    scopes_line = re.search(r"export const SCOPES = \[(.*?)\]", ts, re.S)
    assert scopes_line
    assert set(re.findall(r"'([^']+)'", scopes_line.group(1))) == ALL_SCOPES
    presets = re.findall(
        r"key: '([^']+)',\s*title: '([^']+)',\s*intent: '([^']+)',\s*scopes: \[([^\]]*)\]", ts
    )
    offered = {
        key: (title, intent, frozenset(re.findall(r"'([^']+)'", scopes)))
        for key, title, intent, scopes in presets
    }
    expected = {
        p.key: (p.title, p.intent, frozenset(p.scopes)) for p in PROFILES if p is not WORKER
    }
    assert offered == expected
