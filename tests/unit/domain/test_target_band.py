"""T-DOM-024 / T-DOM-027: band selection by date and training type; training text mapping."""

from datetime import date

import pytest

from victus.domain.services.target_band import select_band, training_type_from_text
from victus.domain.values import Band, TargetBand, TrainingType

pytestmark = pytest.mark.domain

B = Band(min=1, opt_min=2, opt_max=3, target=2.5, max=4)


def _tb(
    name: str, tt: TrainingType | None, frm: date, until: date | None = None, salt_target: float = 7
) -> TargetBand:
    salt = Band(min=4, opt_min=6, opt_max=10, target=salt_target, max=15)
    return TargetBand(name, tt, frm, until, protein=B, carbs=B, fat=B, fiber=B, salt=salt)


BANDS = [
    _tb("v1 rest", TrainingType.REST, date(2026, 1, 1), date(2026, 8, 19), salt_target=5),
    _tb("v2 rest", TrainingType.REST, date(2026, 8, 19), salt_target=7),
    _tb("v2 strength", TrainingType.STRENGTH, date(2026, 8, 19), salt_target=9),
    _tb("v2 martial", TrainingType.MARTIAL_ARTS, date(2026, 8, 19), salt_target=9.5),
]


def test_select_version_valid_at_date() -> None:
    assert select_band(BANDS, date(2026, 5, 1), TrainingType.REST) is BANDS[0]
    assert select_band(BANDS, date(2026, 8, 19), TrainingType.REST) is BANDS[1]
    assert select_band(BANDS, date(2026, 8, 18), TrainingType.REST) is BANDS[0]


def test_select_by_training_type_and_fallbacks() -> None:
    assert select_band(BANDS, date(2026, 9, 1), TrainingType.STRENGTH) is BANDS[2]
    assert select_band(BANDS, date(2026, 9, 1), TrainingType.MARTIAL_ARTS) is BANDS[3]
    assert select_band(BANDS, date(2026, 9, 1), None) is BANDS[1]  # unknown → rest
    assert (
        select_band(BANDS, date(2026, 5, 1), TrainingType.STRENGTH) is BANDS[0]
    )  # v1 had rest only
    assert select_band(BANDS, date(2025, 12, 31), TrainingType.REST) is None


def test_generic_profile_preferred_over_rest_for_unknown_type() -> None:
    generic = _tb("generic", None, date(2026, 1, 1))
    assert select_band([*BANDS, generic], date(2026, 9, 1), None) is generic
    assert select_band([*BANDS, generic], date(2026, 9, 1), TrainingType.STRENGTH) is BANDS[2]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("krafttraining (5x5, verified)", TrainingType.STRENGTH),
        ("kickboxing", TrainingType.MARTIAL_ARTS),
        ("nein (Sauna)", TrainingType.REST),
        ("nein", TrainingType.REST),
        ("rest day", TrainingType.REST),
        ("ja (Aquajogging 60 min)", None),
        ("", None),
        (None, None),
    ],
)
def test_training_type_from_text(text: str | None, expected: TrainingType | None) -> None:
    assert training_type_from_text(text) is expected
