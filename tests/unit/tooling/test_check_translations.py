"""T-TOOL-001: the translation check sees the key wherever the call puts it.

The check is what stands between four languages and an English sentence on a German page,
so it has to find a key that a ternary chooses and it must not invent keys out of the
condition or out of a nested call's arguments. Both went wrong at once: two sentences on
the inbox page were missing from all three dictionaries and the check reported nothing.
"""

from __future__ import annotations

import importlib.util
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


def test_the_repository_itself_passes() -> None:
    """Every key in use has an entry in all three dictionaries."""
    ct = _module()
    used = set(ct.used_strings()) | set(ct.server_strings())
    for language, path in ct.DICTIONARIES.items():
        missing = sorted(used - ct.translated(path))
        assert missing == [], f"{language}: {missing[:5]}"
