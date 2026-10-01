"""Which REST route and which MCP tool a test covers — the registry behind the completeness check.

A test names what it exercises with the ``covers`` marker::

    @pytest.mark.covers("GET /api/v1/days/{day}", "mcp:day_get")
    def test_t_api_013_day_detail(...): ...

A route is written ``"<METHOD> <path template>"`` exactly as the OpenAPI document spells it; an
MCP tool is written ``"mcp:<tool name>"``. The marker also works at module level
(``pytestmark = [pytest.mark.covers(...)]``) and on a ``pytest.param(..., marks=...)``, so a
parametrised scope matrix tags each case with the route or tool it runs against.

The root ``conftest.py`` records every collected test's tags here. The completeness test
(``tests/unit/tooling/test_route_tool_completeness.py``) compares them with the routes of the
app and the tools of the registry: a route or tool nobody tags fails it, and so does a tag that
names no route or tool (a typo, or a route that has since gone).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MARKER = "covers"
MCP_PREFIX = "mcp:"
DUMP_ENV = "VICTUS_COVERS_DUMP"

TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent

#: target → node ids of the tests that tag it, filled while this session collects.
_collected: dict[str, set[str]] = defaultdict(set)
#: every test file this session collected, before any ``-k``/``-m`` deselection.
_collected_files: set[Path] = set()


def mcp(tool: str) -> str:
    """The tag for an MCP tool."""
    return f"{MCP_PREFIX}{tool}"


def targets_of(item: Any) -> set[str]:
    """Every target an item's ``covers`` markers name (function, class, module, param)."""
    found: set[str] = set()
    for mark in item.iter_markers(name=MARKER):
        for arg in mark.args:
            if not isinstance(arg, str):
                raise TypeError(f"{item.nodeid}: covers() takes strings, got {arg!r}")
            found.add(arg)
    return found


def record(items: Iterable[Any]) -> None:
    """Record the tags of a collection (called from ``pytest_collection_modifyitems``)."""
    _collected.clear()
    _collected_files.clear()
    for item in items:
        _collected_files.add(Path(str(item.path)).resolve())
        for target in targets_of(item):
            _collected[target].add(item.nodeid)
    dump = os.environ.get(DUMP_ENV)
    if dump:
        Path(dump).write_text(
            json.dumps({k: sorted(v) for k, v in _collected.items()}, indent=1), encoding="utf-8"
        )


def all_test_files() -> set[Path]:
    return {p.resolve() for p in TESTS_ROOT.rglob("test_*.py")}


def _session_is_complete() -> bool:
    return bool(_collected_files) and all_test_files() <= _collected_files


def collected_targets(tmp_dir: Path) -> dict[str, set[str]]:
    """The tags of the whole suite.

    When this session collected every test file (the normal ``pytest`` run, and CI) the
    session's own record is used. When only a part was selected, the suite is collected once
    more in a subprocess, so running the completeness test on its own gives the same answer.
    """
    if _session_is_complete():
        return {k: set(v) for k, v in _collected.items()}
    dump = tmp_dir / "covers.json"
    env = {**os.environ, DUMP_ENV: str(dump)}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            str(TESTS_ROOT),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not dump.exists():
        raise RuntimeError(f"collecting the suite failed:\n{proc.stdout}\n{proc.stderr}")
    data: dict[str, list[str]] = json.loads(dump.read_text(encoding="utf-8"))
    return {k: set(v) for k, v in data.items()}


def api_routes() -> set[str]:
    """``"<METHOD> <path>"`` for every operation in the app's OpenAPI document."""
    from victus.api.app import create_app
    from victus.config.server import ServerConfig

    with tempfile.TemporaryDirectory() as blobs:
        config = ServerConfig(  # type: ignore[call-arg]
            _env_file=None,
            database={"url": "sqlite://"},
            storage={"path": blobs},
            auth={"rp_id": "localhost", "origin": "http://localhost"},
        )
        app = create_app(config)
        try:
            schema = app.openapi()
        finally:
            app.state.engine.dispose()
    methods = {"get", "post", "put", "patch", "delete"}
    return {
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method in operations
        if method in methods
    }


def mcp_tools() -> set[str]:
    """``"mcp:<name>"`` for every tool in the registry."""
    from victus.mcp.tools import TOOLS

    return {mcp(t.name) for t in TOOLS}
