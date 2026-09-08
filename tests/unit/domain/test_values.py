"""T-DOM-001: value objects behave arithmetically and keep 'not declared' distinct from zero."""

from datetime import date

import pytest

from victus.domain.values import Band, BandZone, Macros, Period

pytestmark = pytest.mark.domain


def test_macros_add_keeps_none_when_both_missing() -> None:
    a = Macros(kcal=100, protein=10)
    b = Macros(kcal=50, salt=None)
    c = a + b
    assert c.kcal == 150
    assert c.protein == 10
    assert c.salt is None  # not declared on either side stays undeclared
    assert c.carbs is None


def test_macros_scaled_and_rounded() -> None:
    m = Macros(kcal=157, protein=7.6, carbs=20.0, fat=4.4, fiber=2.4, salt=1.0).scaled(3.0)
    r = m.rounded()
    assert r.kcal == 471
    assert r.protein == 22.8
    assert r.salt == 3.0


def test_band_zones() -> None:
    b = Band(min=105, opt_min=150, opt_max=185, target=165, max=200, stretch=185)
    assert b.zone(90) is BandZone.BELOW_MIN
    assert b.zone(120) is BandZone.BELOW_OPTIMUM
    assert b.zone(150) is BandZone.OPTIMAL
    assert b.zone(185) is BandZone.OPTIMAL
    assert b.zone(190) is BandZone.ABOVE_OPTIMUM
    assert b.zone(201) is BandZone.ABOVE_MAX


def test_period_days_inclusive() -> None:
    assert Period(date(2026, 1, 1), date(2026, 1, 14)).days == 14
