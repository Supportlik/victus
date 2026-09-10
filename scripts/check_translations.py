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

#: The start of a call; the first argument is then read as an expression.
CALL = re.compile(r"i18n\.t\(")

#: A dictionary key written without quotes: Bare: '...'
BARE_ENTRY = re.compile(r"^\s*(?P<bare>[A-Za-z_]\w*)\s*:")


def _skip_literal(text: str, i: int) -> int:
    """The index just past the literal that starts at ``i``."""
    quote = text[i]
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return i


def _literal_at(text: str, i: int) -> tuple[str, int] | None:
    """The literal starting at ``i`` and the index just past it, or ``None`` for no literal.

    Literals were read with ``(['"])(?:\\\\.|(?!\\1).)*\\1`` until CodeQL pointed out that an
    apostrophe nobody closed makes that pattern backtrack over everything behind it. The scan
    below is the same grammar walked once: it ends at the first unescaped closing quote and
    gives up at the end of the line, which is where the regex gave up too (``.`` never
    matched a newline).

    Unlike ``_skip_literal`` — which answers "where does this string end" for the argument
    scanner and therefore has to return *something* — an unterminated quote is not a literal
    here, so a stray one contributes no key rather than swallowing the rest of the file.
    """
    quote = text[i]
    j = i + 1
    while j < len(text):
        ch = text[j]
        if ch == "\n":
            return None
        if ch == "\\":
            if j + 1 >= len(text) or text[j + 1] == "\n":
                return None
            j += 2
            continue
        if ch == quote:
            return text[i + 1 : j], j + 1
        j += 1
    return None


def _first_argument(text: str, start: int) -> str:
    """The first argument of a call whose "(" has just been consumed.

    Read to the comma that separates it from the parameters, or to the closing
    parenthesis, ignoring anything nested — a key can be built by a ternary, and a
    ternary contains both commas of its own and further calls. Strings are stepped over
    whole: the comma in "Add to this day, or correct it" is part of the sentence.
    """
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "'\"`":
            i = _skip_literal(text, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return text[start:i]
            depth -= 1
        elif ch == "," and depth == 0:
            return text[start:i]
        i += 1
    return text[start:]


#: Where a value may begin: nothing before it, or a branch/fallback operator.
VALUE_POSITION = ("?", ":", "??", "||", "=>")


def _keys_in(text: str, start: int) -> list[str]:
    """The string literals in the first argument that can become the key.

    A literal after `===` is what the key is chosen *by*, and a literal inside brackets
    belongs to a nested call (`kind.replace('_', ' ')`) — neither is a key.
    """
    argument = _first_argument(text, start)
    keys: list[str] = []
    i = 0
    while i < len(argument):
        if argument[i] not in "'\"":
            i += 1
            continue
        literal = _literal_at(argument, i)
        if literal is None:
            i += 1
            continue
        raw, before, i = literal[0], argument[:i], literal[1]
        if before.count("(") > before.count(")") or before.count("[") > before.count("]"):
            continue  # inside a nested call or index
        head = before.rstrip()
        if head and not head.endswith(VALUE_POSITION):
            continue
        keys.append(raw.replace("\\'", "'").replace('\\"', '"'))
    return keys


def used_strings() -> dict[str, list[str]]:
    """Every string passed to ``t()``, with the files it appears in."""
    found: dict[str, list[str]] = {}
    for path in sorted(WEB.rglob("*.ts")) + sorted(WEB.rglob("*.html")):
        if path.name.endswith(".spec.ts") or path in DICTIONARIES.values():
            continue
        text = path.read_text(encoding="utf-8")
        for match in CALL.finditer(text):
            for key in _keys_in(text, match.end()):
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


def _entry_key(line: str) -> str | None:
    """The key a dictionary line defines — ``'text': '…'`` or ``Bare: '…'`` — else ``None``.

    The quoted half is scanned for the same reason as in ``_literal_at``: as a regex it read
    an unclosed quote by backtracking over the line.
    """
    start = len(line) - len(line.lstrip())
    if start < len(line) and line[start] in "'\"":
        literal = _literal_at(line, start)
        if literal is None:
            return None
        raw, end = literal
        if not line[end:].lstrip().startswith(":"):
            return None
        return raw.replace("\\'", "'").replace('\\"', '"')
    match = BARE_ENTRY.match(line)
    return match.group("bare") if match else None


def translated(dictionary: Path) -> set[str]:
    if not dictionary.exists():
        return set()
    keys: set[str] = set()
    for line in dictionary.read_text(encoding="utf-8").splitlines():
        key = _entry_key(line)
        if key is not None:
            keys.add(key)
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
