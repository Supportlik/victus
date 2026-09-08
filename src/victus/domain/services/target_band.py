"""Selecting the target-band profile for a day and mapping training free text."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from victus.domain.values import TargetBand, TrainingType

_STRENGTH = re.compile(
    r"kraft|gzclp|strength|gym|weights?\b|hanteln|bank|kniebeuge|squat|deadlift|kreuzheben",
    re.I,
)
_MARTIAL = re.compile(r"thai|box|kick|mma|kampf|martial|sparring|karate|judo|bjj|ringen", re.I)
_REST = re.compile(
    r"^\s*(nein|no|none|rest|ruhe|ruhetag|pause|-|–|—|0)\b|sauna|spazier|walk|stretch|mobility|yoga",
    re.I,
)


def training_type_from_text(text: str | None) -> TrainingType | None:
    """Map free text such as ``"krafttraining (5x5)"`` or ``"nein (Sauna)"`` to a type.

    Unknown or empty text yields ``None`` — the caller decides on a fallback.
    """
    if text is None:
        return None
    t = text.strip()
    if not t:
        return None
    if _MARTIAL.search(t):
        return TrainingType.MARTIAL_ARTS
    if _STRENGTH.search(t):
        return TrainingType.STRENGTH
    if _REST.search(t):
        return TrainingType.REST
    lowered = t.lower()
    if lowered in {"ja", "yes", "training"}:
        return None
    return None


def select_band(
    bands: Sequence[TargetBand],
    day: date,
    training_type: TrainingType | None,
) -> TargetBand | None:
    """Pick the profile valid on ``day`` for ``training_type``.

    Validity is ``valid_from <= day < valid_until`` (``valid_until`` ``None`` =
    open-ended). Preference: exact training type → profile with ``training_type``
    ``None`` → ``REST`` (the most conservative salt band). Among several valid
    profiles the one with the latest ``valid_from`` wins.
    """
    valid = [
        b for b in bands if b.valid_from <= day and (b.valid_until is None or day < b.valid_until)
    ]
    if not valid:
        return None

    def newest(cands: list[TargetBand]) -> TargetBand | None:
        return max(cands, key=lambda b: b.valid_from) if cands else None

    for wanted in (training_type, None, TrainingType.REST):
        hit = newest([b for b in valid if b.training_type == wanted])
        if hit is not None:
            return hit
    return newest(valid)
