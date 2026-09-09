"""T-SVC-071…072: tape-measure sessions, and the profile the ratios need (R76)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from victus.application.errors import Conflict, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import body as uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases._base import UowFactory
from victus.domain.services.body import Sex

pytestmark = pytest.mark.service

WHEN = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)


def test_a_session_keeps_only_what_was_measured(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-071: a circumference nobody measured stays empty rather than becoming zero."""
    view = uc.AddBodyMeasurement(factory, alice).execute(
        uc.BodyInput(measured_at=WHEN, waist_cm=126.4, hip_cm=118.1, note="tape, morning")
    )
    assert (view.waist_cm, view.hip_cm) == (126.4, 118.1)
    assert view.belly_cm is None and view.arm_cm is None, "not measured is not zero"
    assert view.source == "manual"

    listed = uc.ListBodyMeasurements(factory, alice).execute()
    assert [r.id for r in listed] == [view.id]

    # the same moment twice is a correction, not a second session
    with pytest.raises(Conflict):
        uc.AddBodyMeasurement(factory, alice).execute(
            uc.BodyInput(measured_at=WHEN, waist_cm=126.0)
        )

    # nothing measured at all, and a typo, are both refused
    with pytest.raises(ValidationFailed):
        uc.AddBodyMeasurement(factory, alice).execute(uc.BodyInput(measured_at=WHEN))
    with pytest.raises(ValidationFailed):
        uc.AddBodyMeasurement(factory, alice).execute(
            uc.BodyInput(measured_at=datetime(2026, 9, 8, 8, 0, tzinfo=UTC), waist_cm=1264)
        )

    uc.DeleteBodyMeasurement(factory, alice).execute(view.id)
    assert uc.ListBodyMeasurements(factory, alice).execute() == []


def test_the_profile_reports_what_is_missing(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-072: height, sex and birth date are optional, so every reader must cope."""
    from victus.application.schemas_loader import load_schema

    assert uc.body_profile.__doc__  # documented contract
    with factory(alice) as uow:
        assert uc.body_profile(uow) == (None, None, None)

    data = dict(load_schema("tenant-settings")["examples"][0])
    data["body"] = {"height_cm": 170, "sex": "m", "birth_date": "1990-06-15"}
    settings_uc.PutSettings(factory, alice).execute(data)
    with factory(alice) as uow:
        height, sex, birth = uc.body_profile(uow)
    assert height == 170.0 and sex is Sex.MALE and birth is not None and birth.year == 1990

    # a value the schema allows but the code cannot read must not raise
    data["body"] = {"height_cm": 170}
    settings_uc.PutSettings(factory, alice).execute(data)
    with factory(alice) as uow:
        height, sex, birth = uc.body_profile(uow)
    assert (height, sex, birth) == (170.0, None, None)
