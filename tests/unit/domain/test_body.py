"""T-DOM-081…084: body measures, their classes and the energy split (R76)."""

from __future__ import annotations

import datetime as dt

import pytest

from victus.domain.services.body import (
    Sex,
    age_years,
    basal_rate_kcal,
    bmi,
    bmi_thresholds_kg,
    rate_bmi,
    split_energy,
    waist_to_height,
    waist_to_hip,
    weight_for_bmi,
)

pytestmark = pytest.mark.domain


def test_bmi_and_its_classes() -> None:
    assert bmi(72.0, 180.0) == 22.22
    assert rate_bmi(72.0, 180.0).band.name == "normal weight"
    # the class boundaries are inclusive at the bottom, exclusive at the top
    assert rate_bmi(weight_for_bmi(25.0, 180.0), 180.0).band.name == "overweight"
    assert rate_bmi(80.9, 180.0).band.name == "normal weight", "BMI 24.97"
    assert rate_bmi(weight_for_bmi(40.0, 180.0), 180.0).band.name == "obesity class III"
    assert rate_bmi(50.0, 180.0).band.name == "underweight"


def test_the_distance_to_the_next_better_class_is_in_bmi_points() -> None:
    rated = rate_bmi(100.0, 180.0)  # BMI 30.86, class I
    assert rated.band.name == "obesity class I"
    assert rated.to_next == pytest.approx(0.86, abs=0.01), "0.86 points below class I"
    # someone underweight moves the other way, towards the upper edge of their class
    thin = rate_bmi(weight_for_bmi(17.0, 180.0), 180.0)
    assert thin.to_next == pytest.approx(1.5, abs=0.05)
    # inside the healthy class there is nothing better to reach
    assert rate_bmi(72.0, 180.0).to_next is None


def test_classes_translate_into_kilograms() -> None:
    """A class only becomes actionable as a weight."""
    marks = dict(bmi_thresholds_kg(170.0))
    assert marks["normal weight"] == 53.5
    assert marks["overweight"] == 72.2
    assert marks["obesity class I"] == 86.7
    assert marks["obesity class III"] == 115.6


def test_waist_ratios_use_their_own_scales() -> None:
    assert waist_to_height(85.0, 170.0).value == 0.5
    assert waist_to_height(85.0, 170.0).band.name == "increased"
    assert waist_to_height(84.0, 170.0).band.name == "healthy"
    assert waist_to_height(105.0, 170.0).band.name == "high"

    # the waist to hip thresholds differ by sex
    assert waist_to_hip(88.0, 105.0, Sex.MALE).band.name == "normal", "0.838"
    assert waist_to_hip(88.0, 105.0, Sex.FEMALE).band.name == "normal"
    assert waist_to_hip(95.0, 105.0, Sex.MALE).band.name == "increased", "0.905"
    assert waist_to_hip(95.0, 105.0, Sex.FEMALE).band.name == "high"
    assert waist_to_hip(110.0, 105.0, Sex.MALE).band.name == "high"


def test_age_counts_the_birthday_itself() -> None:
    born = dt.date(1990, 6, 15)
    assert age_years(born, dt.date(2026, 6, 14)) == 35
    assert age_years(born, dt.date(2026, 6, 15)) == 36


def test_basal_rate_follows_mifflin_st_jeor() -> None:
    # 10*80 + 6.25*180 - 5*36 + 5 = 800 + 1125 - 180 + 5
    assert basal_rate_kcal(80.0, 180.0, 36, Sex.MALE) == 1750
    assert basal_rate_kcal(80.0, 180.0, 36, Sex.FEMALE) == 1584


def test_the_energy_split_flags_an_implausible_activity_level() -> None:
    ok = split_energy(2800.0, 1750.0)
    assert (ok.activity_kcal, ok.pal, ok.caveat) == (1050, 1.6, None)

    # below bed rest: the intake is short or too few days count
    low = split_energy(1900.0, 1750.0)
    assert low.pal == 1.09
    assert low.caveat is not None and "bed rest" in low.caveat.key

    # athlete territory
    high = split_energy(4400.0, 1750.0)
    assert high.pal == 2.51
    assert high.caveat is not None and "athlete" in high.caveat.key
