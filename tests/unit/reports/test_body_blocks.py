"""T-REP-030…032: the body blocks compute what they can and name what they cannot (R76)."""

from __future__ import annotations

from datetime import date

import pytest

from victus.application.ports.report_data import BodyProfile, BodySession
from victus.domain.values import Period
from victus.reports.blocks import COMPUTERS
from victus.reports.context import ReportContext
from victus.reports.definition import BodyCompositionDef, EnergySplitDef
from victus.reports.memory_source import InMemoryReportDataSource
from victus.reports.render.markdown import _block
from victus.reports.results import BodyCompositionResult, EnergySplitResult

from .conftest import band_profile, days_from_reference, settings_for

pytestmark = pytest.mark.reports


def _source(ref, **kwargs) -> InMemoryReportDataSource:  # type: ignore[no-untyped-def]
    return InMemoryReportDataSource(
        weights=ref.daily,
        days=days_from_reference(ref),
        settings=settings_for(ref),
        bands=[band_profile(ref)],
        **kwargs,
    )


def _ctx(source: InMemoryReportDataSource, ref) -> ReportContext:  # type: ignore[no-untyped-def]
    end = max(ref.daily)
    return ReportContext(source, Period(end.replace(day=1), end), end)


def _body(ctx: ReportContext) -> BodyCompositionResult:
    block = BodyCompositionDef(type="body_composition", id="body")
    result = COMPUTERS["body_composition"](block, ctx)
    assert isinstance(result, BodyCompositionResult)
    return result


def _energy(ctx: ReportContext) -> EnergySplitResult:
    block = EnergySplitDef(type="energy_split", id="energy")
    result = COMPUTERS["energy_split"](block, ctx)
    assert isinstance(result, EnergySplitResult)
    return result


def test_without_a_profile_nothing_is_invented(ref) -> None:  # type: ignore[no-untyped-def]
    """T-REP-030: a BMI on a guessed height would be worse than no BMI."""
    result = _body(_ctx(_source(ref), ref))
    assert result.bmi is None
    assert result.weight_kg is not None, "the weight itself is known"
    assert any("height" in m for m in result.missing)
    # and the markdown says so rather than showing an empty section
    assert "Not shown" in _block(result)

    energy = _energy(_ctx(_source(ref), ref))
    assert energy.basal_kcal is None
    assert any("height" in m for m in energy.missing)
    assert any("birth date" in m for m in energy.missing)
    assert any("sex" in m for m in energy.missing)


def test_with_a_profile_the_classes_and_thresholds_appear(ref) -> None:  # type: ignore[no-untyped-def]
    """T-REP-031: the classes come out as weights, which is the actionable form."""
    end = max(ref.daily)
    source = _source(
        ref,
        body_profile=BodyProfile(height_cm=180.0, sex="m", birth_date=date(1990, 6, 15)),
        body_sessions=[
            BodySession(measured_at=end.replace(day=1), waist_cm=100.0, hip_cm=110.0),
            BodySession(measured_at=end, waist_cm=96.0, hip_cm=108.0, belly_cm=104.0),
        ],
    )
    result = _body(_ctx(source, ref))
    assert result.bmi is not None and result.bmi.band, "a class was assigned"
    assert result.bmi.bands, "the scale travels with the value"
    assert [m.name for m in result.bmi_weight_bands][:2] == ["underweight", "normal weight"]
    assert result.waist_to_height is not None and result.waist_to_height.value == pytest.approx(
        0.533, abs=0.001
    )
    assert result.waist_to_hip is not None and result.waist_to_hip.band in {
        "normal",
        "increased",
        "high",
    }
    # the change against the previous session, only where both sides measured
    assert result.changes["waist_cm"] == -4.0
    assert "belly_cm" not in result.changes, "the earlier session had no belly value"
    assert result.circumferences["belly_cm"] == 104.0
    assert result.missing == []

    text = _block(result)
    assert "BMI" in text and "Waist to height" in text and "Circumferences" in text


def test_the_energy_split_carries_its_caveat(ref) -> None:  # type: ignore[no-untyped-def]
    """T-REP-032: an impossible activity level is stated, not smoothed over."""
    source = _source(
        ref,
        body_profile=BodyProfile(height_cm=180.0, sex="m", birth_date=date(1990, 6, 15)),
    )
    result = _energy(_ctx(source, ref))
    assert result.tdee_kcal is not None and result.basal_kcal is not None
    assert result.activity_kcal == pytest.approx(result.tdee_kcal - result.basal_kcal, abs=1)
    assert result.pal is not None and result.age_years is not None
    text = _block(result)
    assert "At rest" in text and "Activity level" in text
    if result.caveat:
        assert "⚠️" in text


def test_an_unknown_sex_stops_the_ratio_but_not_the_bmi(ref) -> None:  # type: ignore[no-untyped-def]
    """The schema allows 'x'; there is no third equation, so the block says so."""
    end = max(ref.daily)
    source = _source(
        ref,
        body_profile=BodyProfile(height_cm=180.0, sex="x", birth_date=date(1990, 6, 15)),
        body_sessions=[BodySession(measured_at=end, waist_cm=96.0, hip_cm=108.0)],
    )
    result = _body(_ctx(source, ref))
    assert result.bmi is not None, "the BMI needs no sex"
    assert result.waist_to_hip is None
    assert any("'x'" in m for m in result.missing)

    energy = _energy(_ctx(source, ref))
    assert energy.basal_kcal is None
    assert any("'x'" in m for m in energy.missing)

def test_no_circumference_is_left_out_of_the_change(ref) -> None:  # type: ignore[no-untyped-def]
    """A value that did not move must read as 0.0, not as unmeasured.

    The two lists of circumferences used to be maintained separately, and the neck fell out
    of the one used for changes: a value that had not moved looked like a missing one.
    """
    end = max(ref.daily)
    everything = dict(
        waist_cm=100.0, belly_cm=110.0, hip_cm=105.0, chest_cm=104.0,
        neck_cm=45.0, thigh_cm=60.0, arm_cm=35.0,
    )
    source = _source(
        ref,
        body_profile=BodyProfile(height_cm=180.0, sex="m"),
        body_sessions=[
            BodySession(measured_at=end.replace(day=1), **everything),
            BodySession(measured_at=end, **{**everything, "waist_cm": 98.0}),
        ],
    )
    result = _body(_ctx(source, ref))
    assert set(result.changes) == set(everything), "every measured circumference is compared"
    assert result.changes["waist_cm"] == -2.0
    assert result.changes["neck_cm"] == 0.0
