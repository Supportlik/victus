"""T-SVC-010/011 (locks), T-SVC-017 (settings versions), target-band selection."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from victus.domain.values import TrainingType
from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.service

DAY = date(2026, 4, 1)


def test_t_svc_010_lock_acquire_and_conflict(uow: SqlAlchemyUnitOfWork) -> None:
    now = datetime.now(UTC)
    with uow as u:
        assert u.agent.try_acquire_lock(DAY, "worker", "run-a", 5, now) is True
        assert u.agent.try_acquire_lock(DAY, "external", "run-b", 5, now) is False
        assert (
            u.agent.try_acquire_lock(DAY, "worker", "run-a", 5, now) is True
        )  # re-entrant for the holder
        holder = u.agent.lock_holder(DAY, now)
        assert holder is not None and holder.run_id == "run-a"
        assert u.agent.release_locks("run-a") == 1
        assert u.agent.try_acquire_lock(DAY, "external", "run-b", 5, now) is True


def test_t_svc_011_expired_lock_can_be_taken(uow: SqlAlchemyUnitOfWork) -> None:
    t0 = datetime.now(UTC)
    with uow as u:
        assert u.agent.try_acquire_lock(DAY, "worker", "run-a", 5, t0)
        later = t0 + timedelta(minutes=6)
        assert u.agent.lock_holder(DAY, later) is None
        assert u.agent.try_acquire_lock(DAY, "external", "run-b", 5, later) is True
        holder = u.agent.lock_holder(DAY, later)
        assert holder is not None and holder.run_id == "run-b"


def test_t_svc_017_settings_versions(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        v1 = u.settings.add_version({"kcal_per_kg": 7716.17}, date(2026, 1, 1), "alice")
        v2 = u.settings.add_version({"kcal_per_kg": 7700.0}, date(2026, 3, 1), "alice")
        u.commit()
        assert (v1.version, v2.version) == (1, 2)
        assert u.settings.current() is not None and u.settings.current().version == 2
        assert u.settings.for_date(date(2026, 2, 1)).data["kcal_per_kg"] == 7716.17  # type: ignore[union-attr]
        assert u.settings.for_date(date(2026, 3, 1)).data["kcal_per_kg"] == 7700.0  # type: ignore[union-attr]
        assert u.settings.for_date(date(2025, 12, 31)) is None
        assert [s.version for s in u.settings.versions()] == [1, 2]


def _band(
    u: SqlAlchemyUnitOfWork,
    name: str,
    tt: str | None,
    valid_from: date,
    valid_until: date | None = None,
) -> orm.TargetBand:
    return u.target_bands.add(
        orm.TargetBand(
            tenant_id=u.ctx.tenant_id,
            name=name,
            training_type=tt,
            valid_from=valid_from,
            valid_until=valid_until,
            protein_min=105,
            protein_opt_min=150,
            protein_opt_max=185,
            protein_target=165,
            protein_max=200,
        )
    )


def test_target_band_for_date_prefers_specific_and_latest(uow: SqlAlchemyUnitOfWork) -> None:
    with uow as u:
        _band(u, "generic (no salt target)", None, date(2026, 1, 1), date(2026, 8, 17))
        _band(u, "rest", "rest", date(2026, 8, 18))
        _band(u, "strength", "strength", date(2026, 8, 18))
        u.commit()
        early = u.target_bands.for_date(date(2026, 5, 1), TrainingType.STRENGTH)
        assert early is not None and early.name == "generic (no salt target)"
        later = u.target_bands.for_date(date(2026, 9, 1), TrainingType.STRENGTH)
        assert later is not None and later.name == "strength"
        rest = u.target_bands.for_date(date(2026, 9, 1), TrainingType.REST)
        assert rest is not None and rest.name == "rest"
        # martial arts has no own profile after 08-18 and the generic one has expired.
        # A type that was asked for is never traded for another one: answering with the
        # resting standard would measure a training day against the wrong band.
        assert u.target_bands.for_date(date(2026, 9, 1), TrainingType.MARTIAL_ARTS) is None

        # A day nobody classified is a rest day. Until 08-17 the generic band covers it;
        # after that only the three typed bands exist, and without this the day had no
        # band at all - no targets on the page, every macro unrated in the report.
        unclassified_now = u.target_bands.for_date(date(2026, 9, 1), None)
        assert unclassified_now is not None and unclassified_now.name == "rest"

        # ...but a band that applies to any day is the more deliberate statement, so it
        # wins over the rest band standing in for a missing choice.
        unclassified_then = u.target_bands.for_date(date(2026, 5, 1), None)
        assert unclassified_then is not None
        assert unclassified_then.name == "generic (no salt target)"
