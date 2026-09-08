"""T-DOM-011 / T-DOM-012: band distribution and the asymmetric calorie corridor."""

import pytest

from tests.unit.domain.conftest import Reference
from victus.domain.services.band_rating import (
    band_distribution,
    corridor_counts,
    corridor_rating,
    rate,
)
from victus.domain.values import Band, BandZone, CalorieCorridor

pytestmark = pytest.mark.domain

PROTEIN = Band(min=105, opt_min=150, opt_max=185, target=165, max=200, stretch=185)


def test_distribution_counts_sum_to_n() -> None:
    values = [90, 120, 150, 160, 185, 190, 205, 100.5, 149.9, 185.1]
    s = band_distribution(values, PROTEIN)
    assert (s.below_min, s.below_optimum, s.optimal, s.above_optimum, s.above_max) == (
        2,
        2,
        3,
        2,
        1,
    )
    assert s.n == 10
    assert s.mean == pytest.approx(153.55, abs=0.01)


def test_distribution_matches_predecessor(ref: Reference) -> None:
    """The predecessor reported below/between/optimal/above; 'between' = below_opt + above_opt."""
    b = ref.protein_band
    band = Band(min=b["min"], opt_min=b["opt"][0], opt_max=b["opt"][1], target=165, max=b["max"])
    s = band_distribution(sorted(ref.protein.values()), band)
    exp = ref.out["protein_distribution"]
    assert s.below_min == exp["below_min"]
    assert s.optimal == exp["optimal"]
    assert s.above_max == exp["above_max"]
    assert s.below_optimum + s.above_optimum == exp["between"]
    assert s.n == exp["n"]


def test_empty_distribution() -> None:
    s = band_distribution([], PROTEIN)
    assert s.n == 0 and s.mean is None


def test_rate_delegates_to_band() -> None:
    assert rate(170, PROTEIN) is BandZone.OPTIMAL


def test_asymmetric_corridor() -> None:
    c = CalorieCorridor(1400, 2000, asymmetric=True)
    assert corridor_rating(1200, c) is BandZone.OPTIMAL  # below min is fine
    assert corridor_rating(1700, c) is BandZone.OPTIMAL
    assert corridor_rating(2001, c) is BandZone.ABOVE_MAX
    assert (
        corridor_rating(1200, CalorieCorridor(1400, 2000, asymmetric=False)) is BandZone.BELOW_MIN
    )


def test_corridor_counts() -> None:
    c = CalorieCorridor(1400, 2000)
    assert corridor_counts([1200, 1500, 2500, 2000, 1400], c) == (1, 3, 1)
