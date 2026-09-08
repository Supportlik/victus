"""Locate the JSON Schemas shipped with Victus (``schemas/`` at the repo root).

When installed as a wheel the directory is bundled as ``victus/schemas`` (see
``pyproject.toml``); when running from a checkout the repository copy is used.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

_REPO_SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Return the parsed schema ``<name>.schema.json``."""
    filename = f"{name}.schema.json"
    try:
        pkg = resources.files("victus") / "schemas" / filename
        if pkg.is_file():
            return json.loads(pkg.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    path = _REPO_SCHEMAS / filename
    if not path.is_file():
        raise FileNotFoundError(f"schema {filename} not found")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
