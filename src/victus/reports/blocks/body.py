"""Body composition and the energy split, both derived from measured values (R76)."""

from __future__ import annotations

from victus.domain.services import body as calc
from victus.reports.blocks._meta import meta_for
from victus.reports.context import ReportContext
from victus.reports.definition import BodyCompositionDef, EnergySplitDef
from victus.reports.results import (
    BodyCompositionResult,
    EnergySplitResult,
    RatedValue,
    ThresholdMark,
)


def _rated(rated: calc.Rated, unit: str, decimals: int) -> RatedValue:
    return RatedValue(
        value=round(rated.value, decimals),
        unit=unit,
        band=rated.band.name,
        tone=rated.band.tone,
        to_next=rated.to_next,
        bands=[
            ThresholdMark(name=b.name, lower=b.lower, upper=b.upper, tone=b.tone)
            for b in rated.bands
        ],
    )


def compute_body_composition(
    block: BodyCompositionDef, ctx: ReportContext
) -> BodyCompositionResult:
    """BMI and the waist ratios, each with the scale it was judged against.

    Nothing is guessed: a figure whose input is missing is left out and the reason is
    listed, so the reader knows whether a value is absent or merely unmeasured.
    """
    profile = ctx.body_profile
    sessions = ctx.body_sessions
    latest = sessions[-1] if sessions else None
    previous = sessions[-2] if len(sessions) > 1 else None
    missing: list[str] = []

    weight = ctx.current_kg
    if weight is None:
        missing.append("no weigh-in yet")
    if profile.height_cm is None:
        missing.append("height is not set in the settings")

    bmi: RatedValue | None = None
    marks: list[ThresholdMark] = []
    if weight is not None and profile.height_cm is not None:
        rated = calc.rate_bmi(weight, profile.height_cm)
        bmi = _rated(rated, "", 2)
        # the same classes as weights, which is the form a reader can act on
        marks = [
            ThresholdMark(
                name=b.name,
                lower=calc.weight_for_bmi(b.lower, profile.height_cm) if b.lower else None,
                upper=calc.weight_for_bmi(b.upper, profile.height_cm) if b.upper else None,
                tone=b.tone,
            )
            for b in calc.BMI_BANDS
        ]

    whtr: RatedValue | None = None
    if latest and latest.waist_cm and profile.height_cm:
        whtr = _rated(calc.waist_to_height(latest.waist_cm, profile.height_cm), "", 3)
    elif profile.height_cm and not (latest and latest.waist_cm):
        missing.append("no waist measurement")

    whr: RatedValue | None = None
    if latest and latest.waist_cm and latest.hip_cm and profile.sex:
        try:
            sex = calc.Sex(profile.sex)
        except ValueError:
            missing.append(f"waist to hip has no scale for sex '{profile.sex}'")
        else:
            whr = _rated(calc.waist_to_hip(latest.waist_cm, latest.hip_cm, sex), "", 3)
    elif latest and latest.waist_cm and latest.hip_cm and not profile.sex:
        missing.append("waist to hip needs the sex, which is not set")

    changes: dict[str, float] = {}
    if latest and previous:
        for name in ("waist_cm", "belly_cm", "hip_cm", "chest_cm", "thigh_cm", "arm_cm"):
            now, before = getattr(latest, name), getattr(previous, name)
            if now is not None and before is not None:
                changes[name] = round(now - before, 1)

    return BodyCompositionResult(
        meta=meta_for(block),
        weight_kg=round(weight, 1) if weight is not None else None,
        height_cm=profile.height_cm,
        bmi=bmi,
        bmi_weight_bands=marks,
        waist_to_height=whtr,
        waist_to_hip=whr,
        measured_at=latest.measured_at if latest else None,
        circumferences=(
            {
                name: value
                for name in (
                    "waist_cm",
                    "belly_cm",
                    "hip_cm",
                    "chest_cm",
                    "neck_cm",
                    "thigh_cm",
                    "arm_cm",
                )
                if (value := getattr(latest, name)) is not None
            }
            if latest
            else {}
        ),
        changes=changes,
        body_fat_pct=latest.body_fat_pct if latest else None,
        missing=missing,
    )


def compute_energy_split(block: EnergySplitDef, ctx: ReportContext) -> EnergySplitResult:
    """Split the measured expenditure into the resting rate and everything else.

    The expenditure is the one the weight trend and the logged intake imply, so this says
    how much of it the body spends lying still and how much comes from moving. When the
    ratio is impossible, the caveat says so instead of the number looking authoritative.
    """
    profile = ctx.body_profile
    weight = ctx.current_kg
    reference, basis = ctx.reference_tdee
    missing: list[str] = []
    if reference is None:
        missing.append("no expenditure yet: needs weigh-ins and logged days")
    if weight is None:
        missing.append("no weigh-in yet")
    if profile.height_cm is None:
        missing.append("height is not set in the settings")
    if profile.birth_date is None:
        missing.append("birth date is not set in the settings")
    if not profile.sex:
        missing.append("sex is not set in the settings")

    if reference is None or weight is None or profile.height_cm is None:
        return EnergySplitResult(meta=meta_for(block), basis=basis, missing=missing)
    if profile.birth_date is None or not profile.sex:
        return EnergySplitResult(
            meta=meta_for(block), tdee_kcal=float(reference), basis=basis, missing=missing
        )
    try:
        sex = calc.Sex(profile.sex)
    except ValueError:
        missing.append(f"the resting rate has no equation for sex '{profile.sex}'")
        return EnergySplitResult(
            meta=meta_for(block), tdee_kcal=float(reference), basis=basis, missing=missing
        )

    age = calc.age_years(profile.birth_date, ctx.today)
    basal = calc.basal_rate_kcal(weight, profile.height_cm, age, sex)
    split = calc.split_energy(float(reference), basal)
    return EnergySplitResult(
        meta=meta_for(block),
        tdee_kcal=split.tdee_kcal,
        basal_kcal=split.basal_kcal,
        activity_kcal=split.activity_kcal,
        pal=split.pal,
        age_years=age,
        basis=basis,
        caveat=split.caveat,
        missing=missing,
    )
