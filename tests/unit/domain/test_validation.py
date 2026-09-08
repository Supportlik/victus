"""T-DOM-013 … T-DOM-017: day consistency check — kinds 0–3 and 'not assessable'."""

from datetime import date

import pytest

from victus.domain.model.checks import DayForCheck, Tolerances
from victus.domain.services.validation import check_day, has_errors, is_error
from victus.domain.values import DayStatus, Macros

pytestmark = pytest.mark.domain

D = date(2026, 9, 1)
FULL = Macros(kcal=2000, protein=150, carbs=200, fat=60, fiber=35, salt=7)


def _codes(findings: list) -> list[str]:  # type: ignore[type-arg]
    return [f.code for f in findings]


def test_kind0_missing_flags() -> None:
    f = check_day(DayForCheck(D, None, None, source=FULL))
    assert _codes(f) == ["flags_missing"]
    assert f[0].kind == 0 and has_errors(f)


def test_kind1_drift_uses_relative_kcal_tolerance() -> None:
    """kcal 50 apart is within max(3, 3 % of 2050 = 61.5); protein 0.5 < 0.6; salt 0.05 < 0.06."""
    day = DayForCheck(
        D, True, DayStatus.CLOSED, source=FULL, balance=Macros(kcal=2050, protein=150.5, salt=7.05)
    )
    assert check_day(day) == []


def test_kind1_drift_detected() -> None:
    day = DayForCheck(
        D, True, DayStatus.CLOSED, source=FULL, balance=Macros(kcal=2100, protein=151)
    )
    f = check_day(day)
    macros = sorted(x.details["macro"] for x in f if x.kind == 1)
    assert macros == ["kcal", "protein"]


def test_kind2_meal_totals_mismatch() -> None:
    day = DayForCheck(
        D,
        True,
        DayStatus.CLOSED,
        source=FULL,
        meal_totals=[Macros(kcal=600), Macros(kcal=700), Macros(kcal=600)],
    )
    f = [x for x in check_day(day) if x.kind == 2]
    assert _codes(f) == ["balance_mismatch"]
    assert f[0].details["diff"] == -100


def test_kind2_within_tolerance() -> None:
    day = DayForCheck(
        D, True, DayStatus.CLOSED, source=FULL, meal_totals=[Macros(kcal=1000), Macros(kcal=1050)]
    )
    assert not [x for x in check_day(day) if x.kind == 2]


def test_kind2_not_assessable_is_not_an_error() -> None:
    day = DayForCheck(D, True, DayStatus.CLOSED, source=FULL, meal_totals=[Macros(kcal=600), None])
    f = check_day(day)
    assert _codes(f) == ["not_assessable"]
    assert not is_error(f[0]) and not has_errors(f)


def test_kind2_falls_back_to_item_sum() -> None:
    day = DayForCheck(D, True, DayStatus.CLOSED, source=FULL, item_sum=Macros(kcal=1500))
    f = check_day(day)
    assert _codes(f) == ["balance_mismatch"]


def test_kind3_gaps_and_expected_salt_gap() -> None:
    no_fiber = Macros(kcal=2000, protein=150, carbs=200, fat=60, salt=7)
    f = check_day(DayForCheck(D, True, DayStatus.CLOSED, source=no_fiber))
    assert _codes(f) == ["gap"] and f[0].details["macros"] == "fiber"
    no_salt = Macros(kcal=2000, protein=150, carbs=200, fat=60, fiber=35)
    f = check_day(
        DayForCheck(
            D, True, DayStatus.CLOSED, source=no_salt, salt_tracking_start=date(2026, 9, 15)
        )
    )
    assert _codes(f) == ["expected_gap"] and not has_errors(f)
    f = check_day(
        DayForCheck(D, True, DayStatus.CLOSED, source=no_salt, salt_tracking_start=date(2026, 8, 1))
    )
    assert _codes(f) == ["gap"]


def test_gaps_only_checked_on_countable_days() -> None:
    no_fiber = Macros(kcal=2000)
    assert check_day(DayForCheck(D, False, DayStatus.CLOSED, source=no_fiber)) == []
    assert check_day(DayForCheck(D, True, DayStatus.OPEN, source=no_fiber)) == []


def test_custom_tolerances() -> None:
    day = DayForCheck(D, True, DayStatus.CLOSED, source=FULL, balance=Macros(kcal=2004))
    assert check_day(day) == []
    assert _codes(check_day(day, Tolerances(kcal_abs=1, kcal_rel=0.0))) == ["source_balance_drift"]
