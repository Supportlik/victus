#!/usr/bin/env python
"""Report interface strings that are not translated yet (R78).

The English string is its own key, so a missing translation silently shows English. That
fallback is deliberate, because English is correct rather than broken, but it also means a
gap leaves no trace. This script finds the gap.

It scans the web templates for the strings passed to ``i18n.t(...)`` **and** the Python
source for the keys handed over as ``Message(...)``, then compares both with every
dictionary beside it (German, Spanish, French). Exit code 1 with ``--strict``, so CI can
hold the line once the translation is complete; without it the script only reports.

The server-side half matters as much as the templates: a sentence the server sends is one
the interface has to translate, and nothing in a template mentions it.

    uv run python scripts/check_translations.py
    uv run python scripts/check_translations.py --strict

Two limits are by design. A dynamic key, ``i18n.t(item.label)``, cannot be seen here, so
strings reached that way have to be kept in the dictionary by hand. And an entry listed as
unused may simply be waiting for its template: the dictionary is filled ahead of the views.
The direction that matters is the other one, a ``t()`` call with no translation.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web" / "src" / "app"
PY_SRC = ROOT / "src" / "victus"
#: One dictionary per language; English needs none, it is what the templates already say.
DICTIONARIES = {
    "de": WEB / "core" / "i18n.de.ts",
    "es": WEB / "core" / "i18n.es.ts",
    "fr": WEB / "core" / "i18n.fr.ts",
}

#: i18n.t('...') or i18n.t("..."), the first argument only.
CALL = re.compile(r"""i18n\.t\(\s*(['"])(?P<text>(?:\\.|(?!\1).)*)\1""")

#: Keys in the dictionary: 'text': '...' or Bare: '...'
ENTRY = re.compile(r"^\s*(?:(['\"])(?P<quoted>(?:\\.|(?!\1).)*)\1|(?P<bare>[A-Za-z_][\w]*))\s*:")


def used_strings() -> dict[str, list[str]]:
    """Every string passed to ``t()``, with the files it appears in."""
    found: dict[str, list[str]] = {}
    for path in sorted(WEB.rglob("*.ts")) + sorted(WEB.rglob("*.html")):
        if path.name.endswith(".spec.ts") or path in DICTIONARIES.values():
            continue
        text = path.read_text(encoding="utf-8")
        for match in CALL.finditer(text):
            key = match.group("text").replace("\\'", "'").replace('\\"', '"')
            found.setdefault(key, []).append(str(path.relative_to(ROOT)))
    return found


def server_strings() -> dict[str, list[str]]:
    """Every string a ``Message(...)`` is built from, with the files it appears in.

    Parsed rather than matched: a key written across two lines is one string to Python and
    should be one string here too.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(PY_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else None
            if name != "Message" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.setdefault(first.value, []).append(str(path.relative_to(ROOT)))
    return found


def translated(dictionary: Path) -> set[str]:
    if not dictionary.exists():
        return set()
    keys: set[str] = set()
    for line in dictionary.read_text(encoding="utf-8").splitlines():
        match = ENTRY.match(line)
        if match:
            raw = match.group("quoted") or match.group("bare") or ""
            keys.add(raw.replace("\\'", "'").replace('\\"', '"'))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="fail when anything is missing")
    args = parser.parse_args()

    used = used_strings()
    server = server_strings()
    for key, where in server.items():
        used.setdefault(key, []).extend(where)
    print(f"strings in use: {len(used)} ({len(server)} of them sent by the server)")
    gaps = 0
    for code, path in DICTIONARIES.items():
        have = translated(path)
        missing = sorted(k for k in used if k not in have)
        unused = sorted(k for k in have if k not in used)
        gaps += len(missing)
        print(f"\n{code}: {len(have)} entries")
        if missing:
            print(f"  not translated ({len(missing)}):")
            for key in missing:
                print(f"    {key!r}  ({used[key][0]})")
        if unused:
            print(f"  in the dictionary but no longer used ({len(unused)}):")
            for key in unused:
                print(f"    {key!r}")
        if not missing and not unused:
            print("  complete")
    return 1 if (args.strict and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
