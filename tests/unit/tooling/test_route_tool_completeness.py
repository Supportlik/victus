"""T-TOOL-100…102: every REST route and every MCP tool has a test tagged for it.

Line coverage says a line ran; it does not say that anybody checked what a route answers.
The completeness check reads the ``covers`` tags of the whole suite (see
``tests/coverage_registry.py``) and compares them with the operations in the OpenAPI document
and the tools in the MCP registry. A new route or tool without a tagged test fails here, and so
does a tag naming something that does not exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import coverage_registry

pytestmark = pytest.mark.domain


@pytest.fixture(scope="module")
def tags(tmp_path_factory: pytest.TempPathFactory) -> dict[str, set[str]]:
    return coverage_registry.collected_targets(Path(tmp_path_factory.mktemp("covers")))


def test_t_tool_100_every_route_has_a_test(tags: dict[str, set[str]]) -> None:
    """T-TOOL-100: every operation in the OpenAPI document is named by a ``covers`` tag."""
    missing = sorted(coverage_registry.api_routes() - tags.keys())
    assert not missing, "routes without a tagged test:\n  " + "\n  ".join(missing)


def test_t_tool_101_every_mcp_tool_has_a_test(tags: dict[str, set[str]]) -> None:
    """T-TOOL-101: every tool of the MCP registry is named by a ``covers("mcp:<name>")`` tag."""
    missing = sorted(coverage_registry.mcp_tools() - tags.keys())
    assert not missing, "MCP tools without a tagged test:\n  " + "\n  ".join(missing)


def test_t_tool_102_every_tag_names_a_route_or_tool(tags: dict[str, set[str]]) -> None:
    """T-TOOL-102: a tag that names no route and no tool is a typo or a route that went."""
    known = coverage_registry.api_routes() | coverage_registry.mcp_tools()
    unknown = {t: sorted(nodes) for t, nodes in tags.items() if t not in known}
    assert not unknown, f"covers() tags naming nothing: {unknown}"
