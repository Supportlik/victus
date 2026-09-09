#!/usr/bin/env python3
"""Fail if the working tree contains personal data (SPEC R48 / D16).

Two layers:

1. **Generic patterns**, always on: routable IPv4 addresses, private e-mail
   providers, and phrases that look like a body metric attached to a date.
2. **A private denylist**, optional: one term per line in the file named by the
   ``VICTUS_PRIVACY_DENYLIST`` environment variable. The list itself must live
   *outside* the repository — publishing it would publish exactly the words it
   is meant to keep out.

Usage: ``python scripts/privacy_check.py [PATH ...]`` (defaults to the repo).
Exit code 1 on findings, 0 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    ".angular",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}
# This file names the very things it looks for.
SKIP_FILES = {"uv.lock", "package-lock.json", "privacy_check.py"}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ts",
    ".html",
    ".scss",
    ".css",
    ".sh",
    ".txt",
    ".cfg",
    ".ini",
    ".env",
    ".example",
    "",
}

# Documentation / loopback / private ranges are fine; anything else routable is suspicious.
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ALLOWED_IP_PREFIXES = (
    "127.",
    "0.0.0.0",
    "10.",
    "192.168.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.2",
    "172.30.",
    "172.31.",
    "203.0.113.",
    "198.51.100.",
    "192.0.2.",
    "100.64.0.0",
    "255.",
)
PRIVATE_MAIL = re.compile(
    r"[\w.+-]+@(gmail|googlemail|outlook|hotmail|gmx|web|yahoo|icloud|proton)\.\w+", re.I
)
#: A hostname in a private zone belongs to somebody; only count it where it is
#: written as one — inside a string or a URL, not `this.local.set(...)`.
PRIVATE_HOST = re.compile(
    "(?:https?://|[\"'`])[A-Za-z0-9-]+\\.(?:home|lan|local|internal)\\.[A-Za-z]{2,24}\\b",
    re.I,
)
#: The maintainer's own name has no business in the code, not even as a fixture.
OWN_NAME = re.compile(r"\b(michael|bortlik)\b", re.I)
BODY_METRIC = re.compile(
    r"\b\d{2,3}([.,]\d)?\s?kg\b.*\b20\d\d-\d\d-\d\d\b|\b20\d\d-\d\d-\d\d\b.*\b\d{2,3}([.,]\d)?\s?kg\b",
    re.I,
)

# Files that legitimately contain example numbers and dates.
EXAMPLE_FILES = {"examples", "docs", "tests"}

# Where the maintainer's name belongs: it is the copyright holder's name, and the
# licence is worth nothing without it. Anywhere else it is a leak.
NAME_ALLOWED = {"LICENSE", "README.md", "CONTRIBUTING.md", "pyproject.toml"}


def iter_files(paths: list[Path]):
    for base in paths:
        if base.is_file():
            yield base
            continue
        for p in base.rglob("*"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file() and p.name not in SKIP_FILES and p.suffix.lower() in TEXT_SUFFIXES:
                yield p


def load_denylist() -> list[str]:
    path = os.environ.get("VICTUS_PRIVACY_DENYLIST")
    if not path:
        return []
    terms = [t.strip() for t in Path(path).read_text(encoding="utf-8").splitlines()]
    return [t for t in terms if t and not t.startswith("#")]


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] or [ROOT]
    denylist = load_denylist()
    findings: list[str] = []
    for file in iter_files(targets):
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = file.relative_to(ROOT) if file.is_relative_to(ROOT) else file
        in_examples = rel.parts and rel.parts[0] in EXAMPLE_FILES
        for lineno, line in enumerate(text.splitlines(), 1):
            for ip in IPV4.findall(line):
                if not ip.startswith(ALLOWED_IP_PREFIXES):
                    findings.append(f"{rel}:{lineno}: routable IPv4 address {ip}")
            if PRIVATE_MAIL.search(line):
                findings.append(f"{rel}:{lineno}: private e-mail address")
            if host := PRIVATE_HOST.search(line):
                findings.append(f"{rel}:{lineno}: host in a private zone ({host.group(0)})")
            if rel.name not in NAME_ALLOWED and (name := OWN_NAME.search(line)):
                findings.append(f"{rel}:{lineno}: the maintainer's own name ({name.group(0)})")
            if not in_examples and BODY_METRIC.search(line):
                findings.append(f"{rel}:{lineno}: body metric next to a date")
            low = line.lower()
            for term in denylist:
                if term.lower() in low:
                    findings.append(f"{rel}:{lineno}: denylisted term")
    if findings:
        print("privacy check: FAILED")
        print("\n".join(findings))
        return 1
    extra = f" (+{len(denylist)} private terms)" if denylist else ""
    print(f"privacy check: ok{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
