"""Read the "Scope profiles" section of ``docs/API.md`` the way a person setting up a token does.

Each ``#### <title>`` block names its scopes (``Scopes: `…` ``), a CLI command and three
lists of backticked names — MCP tools or ``METHOD /path`` routes:

- ``Can`` — allowed, and the result is what the call says;
- ``Becomes a proposal or a draft`` — allowed, but without ``approve`` not a fact;
- ``Refused`` — not allowed (for the worker: also not handed to the model).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "API.md"
_ROUTE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /\S+$")


@dataclass
class DocumentedProfile:
    title: str
    scopes: str = ""
    command: str = ""
    lists: dict[str, list[str]] = field(default_factory=dict)

    def tools(self, kind: str) -> list[str]:
        return [n for n in self.lists.get(kind, []) if not _ROUTE.match(n)]

    def routes(self, kind: str) -> list[str]:
        return [n for n in self.lists.get(kind, []) if _ROUTE.match(n)]


KINDS = {"Can": "can", "Becomes a proposal or a draft": "fallback", "Refused": "refused"}


def documented_profiles(text: str | None = None) -> dict[str, DocumentedProfile]:
    text = text if text is not None else DOC.read_text(encoding="utf-8")
    section = text.split("### Scope profiles", 1)[1].split("\n## ", 1)[0]
    out: dict[str, DocumentedProfile] = {}
    current: DocumentedProfile | None = None
    for line in section.splitlines():
        if line.startswith("#### "):
            current = DocumentedProfile(line[5:].strip())
            out[current.title] = current
            continue
        if current is None:
            continue
        if line.startswith("Scopes: `") and not current.scopes:
            current.scopes = line.split("`")[1]
        elif "--scopes" in line or line.startswith("victus worker"):
            current.command = line.strip()
        m = re.match(r"- \*\*(.+?):\*\* (.*)$", line)
        if m and m.group(1) in KINDS:
            # a parenthesis explains an item; only the backticked names count
            names = re.findall(r"`([^`]+)`", re.sub(r"\([^)]*\)", "", m.group(2)))
            current.lists[KINDS[m.group(1)]] = names
    return out
