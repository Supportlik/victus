"""T-DOM-000: the domain layer must stay free of framework and I/O imports.

Walks every module under ``victus.domain`` and asserts that no import points at
the application/infrastructure/api layers or at SQLAlchemy/Pydantic/FastAPI.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import victus.domain

FORBIDDEN_PREFIXES = (
    "victus.application",
    "victus.infrastructure",
    "victus.api",
    "victus.mcp",
    "victus.agent",
    "sqlalchemy",
    "pydantic",
    "fastapi",
    "httpx",
    "requests",
)

pytestmark = pytest.mark.domain


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_domain_has_no_framework_imports() -> None:
    root = Path(victus.domain.__file__).parent
    offenders: list[str] = []
    for py in root.rglob("*.py"):
        for name in _imports(py):
            if name.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{py.relative_to(root)}: {name}")
    assert not offenders, "domain layer imports forbidden modules:\n" + "\n".join(offenders)
