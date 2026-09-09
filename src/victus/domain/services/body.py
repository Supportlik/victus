"""Body measures derived from weight, height and circumferences (R76).

Everything here is a pure function over numbers that are measured elsewhere. Each result
carries the classification behind it and the thresholds it was judged against, so a report
can show where a value sits rather than only what it is, and a reader can see which scale
was applied.

Sources for the thresholds:

- BMI classes: WHO, *Obesity: preventing and managing the global epidemic* (2000).
- Waist to height: NICE guideline CG189 / NG246, "keep your waist under half your height".
- Waist to hip: WHO, *Waist circumference and waist-hip ratio* (2008), sex-specific.
- Basal rate: Mifflin-St Jeor (1990), the equation with the smallest error in validation
  studies of the common ones.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from victus.domain.values import Message


class Sex(StrEnum):
    """Only what the equations distinguish, with the codes the settings schema uses.

    The schema also allows ``x``. There is no third variant of the Mifflin-St Jeor
    equation, so ``x`` yields no sex here and the resting rate is left uncomputed rather
    than silently assigned to one of the two.
    """

    MALE = "m"
    FEMALE = "f"


@dataclass(frozen=True, slots=True)
class Band:
    """One class of a scale. ``upper`` None means the class is open at the top."""

    name: str
    lower: float | None
    upper: float | None
    #: How this class reads: ok, watch, warn, bad. Charts and tiles colour by this.
    tone: str

    def contains(self, value: float) -> bool:
        if self.lower is not None and value < self.lower:
            return False
        return not (self.upper is not None and value >= self.upper)


@dataclass(frozen=True, slots=True)
class Rated:
    """A value, the class it falls in, and the scale it was judged against."""

    value: float
    band: Band
    bands: tuple[Band, ...]
    #: Distance to the next better class, in the value's own unit; None when already best.
    to_next: float | None = None


#: WHO classes. The names are the ones used in clinical practice, not softened.
BMI_BANDS: tuple[Band, ...] = (
    Band("underweight", None, 18.5, "warn"),
    Band("normal weight", 18.5, 25.0, "ok"),
    Band("overweight", 25.0, 30.0, "watch"),
    Band("obesity class I", 30.0, 35.0, "warn"),
    Band("obesity class II", 35.0, 40.0, "warn"),
    Band("obesity class III", 40.0, None, "bad"),
)

#: Waist divided by height. Sex-independent, and the simplest useful measure of the fat
#: that sits around the organs.
WHTR_BANDS: tuple[Band, ...] = (
    Band("low", None, 0.40, "watch"),
    Band("healthy", 0.40, 0.50, "ok"),
    Band("increased", 0.50, 0.60, "warn"),
    Band("high", 0.60, None, "bad"),
)

#: Waist divided by hip, WHO thresholds, which differ by sex.
WHR_BANDS_MALE: tuple[Band, ...] = (
    Band("normal", None, 0.90, "ok"),
    Band("increased", 0.90, 1.00, "warn"),
    Band("high", 1.00, None, "bad"),
)
WHR_BANDS_FEMALE: tuple[Band, ...] = (
    Band("normal", None, 0.85, "ok"),
    Band("increased", 0.85, 0.90, "warn"),
    Band("high", 0.90, None, "bad"),
)


def _rate(value: float, bands: tuple[Band, ...]) -> Rated:
    band = next((b for b in bands if b.contains(value)), bands[-1])
    index = bands.index(band)
    # "better" means towards the ok class, which may lie either side of the value
    ok_index = next((i for i, b in enumerate(bands) if b.tone == "ok"), 0)
    to_next: float | None = None
    if index > ok_index and band.lower is not None:
        to_next = round(value - band.lower, 3)
    elif index < ok_index and band.upper is not None:
        to_next = round(band.upper - value, 3)
    return Rated(value=value, band=band, bands=bands, to_next=to_next)


def bmi(weight_kg: float, height_cm: float) -> float:
    """Weight over height squared. Raises on nonsense rather than returning it."""
    if weight_kg <= 0 or height_cm <= 0:
        raise ValueError("weight and height must be positive")
    metres = height_cm / 100.0
    return round(weight_kg / (metres * metres), 2)


def rate_bmi(weight_kg: float, height_cm: float) -> Rated:
    return _rate(bmi(weight_kg, height_cm), BMI_BANDS)


def weight_for_bmi(target_bmi: float, height_cm: float) -> float:
    """The weight a BMI corresponds to at this height, so a class becomes a kilogram."""
    metres = height_cm / 100.0
    return round(target_bmi * metres * metres, 1)


def bmi_thresholds_kg(height_cm: float) -> list[tuple[str, float]]:
    """Each BMI class boundary as a weight, for charts and for "how far to the next class"."""
    out: list[tuple[str, float]] = []
    for band in BMI_BANDS:
        if band.lower is not None:
            out.append((band.name, weight_for_bmi(band.lower, height_cm)))
    return out


def waist_to_height(waist_cm: float, height_cm: float) -> Rated:
    if waist_cm <= 0 or height_cm <= 0:
        raise ValueError("waist and height must be positive")
    return _rate(round(waist_cm / height_cm, 3), WHTR_BANDS)


def waist_to_hip(waist_cm: float, hip_cm: float, sex: Sex) -> Rated:
    if waist_cm <= 0 or hip_cm <= 0:
        raise ValueError("waist and hip must be positive")
    bands = WHR_BANDS_MALE if sex is Sex.MALE else WHR_BANDS_FEMALE
    return _rate(round(waist_cm / hip_cm, 3), bands)


def age_years(birth_date: dt.date, on: dt.date) -> int:
    """Whole years, counting the birthday itself."""
    had_birthday = (on.month, on.day) >= (birth_date.month, birth_date.day)
    return on.year - birth_date.year - (0 if had_birthday else 1)


def basal_rate_kcal(weight_kg: float, height_cm: float, age: int, sex: Sex) -> float:
    """Resting energy per day, Mifflin-St Jeor.

    This is what the body spends lying still. It is not a target and not a floor for
    eating; it is the reference the rest is measured against.
    """
    if weight_kg <= 0 or height_cm <= 0 or age < 0:
        raise ValueError("weight, height and age must be positive")
    base = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age
    return round(base + (5.0 if sex is Sex.MALE else -161.0), 0)


@dataclass(frozen=True, slots=True)
class EnergySplit:
    """How a measured expenditure divides into resting and everything else."""

    tdee_kcal: float
    basal_kcal: float
    activity_kcal: float
    #: Physical activity level: expenditure over resting. 1.4 sedentary, 1.8 active.
    pal: float
    #: Set when the numbers do not hang together; the report shows it beside the values.
    caveat: Message | None = None


def split_energy(tdee_kcal: float, basal_kcal: float) -> EnergySplit:
    """Split a measured expenditure, and say so when the split is implausible.

    A PAL below 1.2 is lower than bed rest and a PAL above 2.4 is athlete territory, so
    either the weight trend or the intake behind the expenditure is off. Saying that is
    more useful than presenting a tidy but wrong activity figure.
    """
    if basal_kcal <= 0:
        raise ValueError("basal rate must be positive")
    pal = round(tdee_kcal / basal_kcal, 2)
    caveat: Message | None = None
    if pal < 1.2:
        caveat = Message(
            "expenditure is only {pal} times the resting rate, below bed rest: the intake "
            "is probably logged short, or too few days are countable",
            {"pal": pal},
        )
    elif pal > 2.4:
        caveat = Message(
            "expenditure is {pal} times the resting rate, which is athlete territory: "
            "check the weigh-ins and the logged intake",
            {"pal": pal},
        )
    return EnergySplit(
        tdee_kcal=round(tdee_kcal, 0),
        basal_kcal=round(basal_kcal, 0),
        activity_kcal=round(tdee_kcal - basal_kcal, 0),
        pal=pal,
        caveat=caveat,
    )
