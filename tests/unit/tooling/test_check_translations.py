"""T-TOOL-001: the translation check sees the key wherever the call puts it; T-TOOL-002: it
reads literals by scanning them.

The check is what stands between four languages and an English sentence on a German page,
so it has to find a key that a ternary chooses and it must not invent keys out of the
condition or out of a nested call's arguments. Both went wrong at once: two sentences on
the inbox page were missing from all three dictionaries and the check reported nothing.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.domain

ROOT = Path(__file__).resolve().parents[3]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_translations", ROOT / "scripts" / "check_translations.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def keys(source: str) -> list[str]:
    """The keys the check would take from one line of a template."""
    ct = _module()
    at = source.index("i18n.t(") + len("i18n.t(")
    return ct._keys_in(source, at)


def test_a_plain_call_gives_its_one_key() -> None:
    assert keys("{{ i18n.t('Add a capture') }}") == ["Add a capture"]


def test_a_comma_inside_the_sentence_is_not_the_end_of_the_argument() -> None:
    """Scanning for the argument boundary without knowing about strings lost 46 keys."""
    line = "[placeholder]=\"i18n.t('Add to this day, or correct it: 300 g, not 400')\""
    assert keys(line) == ["Add to this day, or correct it: 300 g, not 400"]


def test_both_branches_of_a_ternary_are_keys_and_the_condition_is_not() -> None:
    line = "{{ i18n.t(m.role === 'agent' ? 'Agent' : 'System') }}"
    assert keys(line) == ["Agent", "System"]


def test_a_nested_call_keeps_its_own_arguments() -> None:
    line = "{{ i18n.t(kind.replace('_', ' ')) }}"
    assert keys(line) == [], "'_' and ' ' are arguments to replace, not keys"


def test_parameters_are_not_keys() -> None:
    line = "{{ i18n.t('{n} days left', { n: left() }) }}"
    assert keys(line) == ["{n} days left"]


def test_a_fallback_is_a_key() -> None:
    line = "{{ i18n.t(label() ?? 'Unnamed') }}"
    assert keys(line) == ["Unnamed"]


def test_an_escaped_quote_stays_inside_the_key() -> None:
    """T-TOOL-002: the key is the sentence the template shows, apostrophe included."""
    assert keys("{{ i18n.t('It\\'s open') }}") == ["It's open"]
    assert keys('{{ i18n.t("He said \\"no\\"") }}') == ['He said "no"']


def test_a_quote_nobody_closed_yields_no_key() -> None:
    """T-TOOL-002: an unclosed quote is not a literal, and must not become one by search.

    The pattern this replaced could reach the same conclusion only by backtracking over
    everything behind the quote, which on a file-sized string is what CodeQL reported as
    exponential (alerts #49, #50). The scan stops at the end of the line, as the pattern's
    ``.`` did.
    """
    assert keys("{{ i18n.t('Add a capture) }}") == []
    assert keys("{{ i18n.t('spans\nlines') }}") == []


def test_a_quote_storm_does_not_stall_the_check() -> None:
    """T-TOOL-002: 26 escape pairs behind an unclosed quote took the old pattern ~8 s."""
    bomb = "i18n.t('" + "\\a" * 26 + ")"
    start = time.perf_counter()
    assert keys(bomb) == []
    assert time.perf_counter() - start < 1.0


def test_dictionary_entries_are_read_quoted_and_bare(tmp_path: Path) -> None:
    """T-TOOL-002: the key side of a dictionary line, however it is written."""
    ct = _module()
    path = tmp_path / "i18n.xx.ts"
    path.write_text(
        "export const XX: Record<string, string> = {\n"
        "  'Add to this day, or correct it: 300 g': 'Y',\n"
        "  Agent: 'Y',\n"
        "  \"It's open\": 'Y',\n"
        "  'It\\'s closed': 'Y',\n"
        "  // a comment is not an entry\n"
        "  'never closed: 'Y',\n"
        "};\n",
        encoding="utf-8",
    )
    assert ct.translated(path) == {
        "Add to this day, or correct it: 300 g",
        "Agent",
        "It's open",
        "It's closed",
    }


def test_the_repository_itself_passes() -> None:
    """Every key in use has an entry in all three dictionaries."""
    ct = _module()
    used = set(ct.used_strings()) | set(ct.server_strings())
    for language, path in ct.DICTIONARIES.items():
        missing = sorted(used - ct.translated(path))
        assert missing == [], f"{language}: {missing[:5]}"
