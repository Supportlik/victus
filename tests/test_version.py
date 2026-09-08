"""T-OPS-001: version stamp is a valid PEP 440 string and matches package metadata."""

import importlib.metadata as md
import re

import victus


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", victus.__version__)


def test_version_matches_metadata() -> None:
    assert md.version("victus") == victus.__version__
