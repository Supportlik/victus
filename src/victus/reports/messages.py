"""Sentences a report hands to the interface: a key and its parameters (R78).

A report used to write its own prose — "from the rolling 14-day window" — which the
interface could only show in English. The key is still that sentence, so nothing is lost
for Markdown or the CLI, but a dictionary can now reach it.
"""

from __future__ import annotations

import re

from victus.domain.values import Message

_ROLLING = re.compile(r"rolling_(\d+)d")
_WEEKLY = re.compile(r"weekly_mean_(\d+)w")


def basis_message(basis: str) -> Message:
    """The reference basis in words; ``rolling_14d`` reads like a column name."""
    rolling = _ROLLING.fullmatch(basis)
    if rolling:
        return Message("from the rolling {n}-day window", {"n": int(rolling.group(1))})
    weekly = _WEEKLY.fullmatch(basis)
    if weekly:
        return Message("mean of the last {n} weekly values", {"n": int(weekly.group(1))})
    if basis == "none":
        return Message("no basis yet")
    return Message(basis)


def tdee_from(basis: str) -> Message:
    """The same, as the note under a figure that was derived from it."""
    rolling = _ROLLING.fullmatch(basis)
    if rolling:
        return Message("TDEE from the rolling {n}-day window", {"n": int(rolling.group(1))})
    weekly = _WEEKLY.fullmatch(basis)
    if weekly:
        return Message("TDEE from the mean of {n} weekly values", {"n": int(weekly.group(1))})
    return Message("TDEE, no basis yet")
