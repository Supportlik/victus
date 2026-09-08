"""Rating values against target bands and the asymmetric calorie corridor."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from victus.domain.model.reporting import BandStat
from victus.domain.values import Band, BandZone, CalorieCorridor


def rate(value: float, band: Band) -> BandZone:
    return band.zone(value)


def band_distribution(values: Sequence[float], band: Band) -> BandStat:
    """Count how many values fall into each zone (predecessor: ``band_verteilung``).

    The predecessor reported *below min / between / optimal / above max*; the
    "between" bucket is split here into below- and above-optimum, which sums to
    the same number.
    """
    counts = dict.fromkeys(BandZone, 0)
    for v in values:
        counts[band.zone(v)] += 1
    return BandStat(
        below_min=counts[BandZone.BELOW_MIN],
        below_optimum=counts[BandZone.BELOW_OPTIMUM],
        optimal=counts[BandZone.OPTIMAL],
        above_optimum=counts[BandZone.ABOVE_OPTIMUM],
        above_max=counts[BandZone.ABOVE_MAX],
        mean=round(statistics.mean(values), 2) if values else None,
        n=len(values),
    )


def corridor_rating(mean_kcal: float, corridor: CalorieCorridor) -> BandZone:
    """Rate the *average* intake against the corridor.

    With ``asymmetric=True`` only exceeding the maximum is a finding
    (``ABOVE_MAX``); being below the minimum is ``OPTIMAL`` because the lower
    bound is a band edge, not a target. With ``asymmetric=False`` values below
    the minimum are ``BELOW_MIN``.
    """
    if mean_kcal > corridor.max:
        return BandZone.ABOVE_MAX
    if mean_kcal < corridor.min and not corridor.asymmetric:
        return BandZone.BELOW_MIN
    return BandZone.OPTIMAL


def corridor_counts(values: Sequence[float], corridor: CalorieCorridor) -> tuple[int, int, int]:
    """``(above, within, below)`` day counts for a kcal series."""
    above = sum(1 for v in values if v > corridor.max)
    below = sum(1 for v in values if v < corridor.min)
    return above, len(values) - above - below, below
