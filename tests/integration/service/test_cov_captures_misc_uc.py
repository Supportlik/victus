"""T-SVC-432…438, 453: capture, body-profile, rule and snapshot use cases at their edges."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.service.test_cov_days_uc import SETTINGS
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import body as body_uc
from victus.application.use_cases import captures as uc
from victus.application.use_cases import rules as rules_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases import snapshots as snapshots_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db import orm
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription

pytestmark = pytest.mark.service

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


def _settings_uow(data: dict[str, Any] | None) -> Any:
    """A unit of work whose only use is ``settings.current()``."""
    current = SimpleNamespace(data=data) if data is not None else None
    return SimpleNamespace(settings=SimpleNamespace(current=lambda: current))


def _upload(factory: UowFactory, ctx: TenantContext, blobs: InMemoryBlobStorage, **kw: Any) -> Any:
    return uc.UploadCapture(factory, ctx, blobs).execute(uc.UploadInput(**kw))


def test_t_svc_432_pure_capture_helpers() -> None:
    """T-SVC-432: an unknown extension or no name falls back to octet-stream; a transcription
    section that is not a mapping gives no language or prompt; an invalid retention keeps
    the default; a legacy single attachment is still found; a transcript without a part id
    marks nothing when there are no parts."""
    assert uc.sniff_mime(None, "notes.xyz") == "application/octet-stream"
    assert uc.sniff_mime("", None) == "application/octet-stream"
    assert uc.transcription_settings(_settings_uow({"transcription": "en"})) == (None, None)
    default = timedelta(days=uc.PROCESSED_RETENTION_DEFAULT_DAYS)
    for raw in (-1, "ten", True):
        uow = _settings_uow({"captures": {"processed_retention_days": raw}})
        assert uc.processed_retention(uow) == default

    voice = SimpleNamespace(id="att1", mime="audio/ogg")
    legacy = SimpleNamespace(
        captures=SimpleNamespace(attachments_of=lambda _cid: [], get_attachment=lambda _aid: voice)
    )
    cap = SimpleNamespace(id="cap1", attachment_id="att1")
    assert uc._audio_parts(legacy, cap) == [voice]  # type: ignore[arg-type]
    gone = SimpleNamespace(
        captures=SimpleNamespace(attachments_of=lambda _cid: [], get_attachment=lambda _aid: None)
    )
    assert uc._audio_parts(gone, cap) == []  # type: ignore[arg-type]
    assert uc._already_transcribed([SimpleNamespace(attachment_id=None)], []) == set()  # type: ignore[list-item]


def test_t_svc_433_update_status_product_and_missing_blob(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-433: setting a capture back to ``new`` leaves it unsettled; an unknown product
    is 404; an attachment whose file is gone is 404, not a crash."""
    blobs = InMemoryBlobStorage()
    photo = _upload(factory, alice, blobs, data=PNG, filename="label.png", mime="image/png")
    back = uc.UpdateCapture(factory, alice).execute(photo.id, {"status": "new"})
    assert back.status == "new"
    with pytest.raises(NotFound, match="product 999999"):
        uc.UpdateCapture(factory, alice).execute(photo.id, {"product_id": 999_999})
    blobs.blobs.clear()
    with pytest.raises(NotFound, match="missing"):
        uc.GetAttachment(factory, alice, blobs).execute(photo.attachment_id)


def test_t_svc_434_purge_keeps_shared_files_and_runs_without_storage(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-SVC-434: purging a discarded capture keeps a file another capture still uses, and
    a purge without blob storage removes the rows alone."""
    blobs = InMemoryBlobStorage()
    first = _upload(
        factory, alice, blobs, text="first", data=PNG, filename="a.png", mime="image/png"
    )
    second = _upload(
        factory, alice, blobs, text="second", data=PNG, filename="a.png", mime="image/png"
    )
    assert first.id != second.id
    past = datetime(2026, 1, 1, tzinfo=UTC)
    with session_factory() as s:
        row = s.get(orm.Capture, first.id)
        assert row is not None
        row.status, row.processed_at = "discarded", past
        s.commit()
    with factory(alice) as uow:
        assert uc.purge_settled(uow, blobs, past + timedelta(days=5)) == 1
        uow.commit()
    assert blobs.blobs, "the second capture still needs the photo"

    uc.UpdateCapture(factory, alice).execute(second.id, {"status": "discarded"})
    with factory(alice) as uow:
        assert uc.purge_settled(uow, None, datetime.now(UTC) + timedelta(days=5)) == 1
        uow.commit()


def test_t_svc_435_transcription_needs_audio_and_its_file(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-SVC-435: an audio capture without a recording, and one whose recording is gone
    from storage, are refused with what is missing."""
    blobs = InMemoryBlobStorage()
    fake = FakeTranscription()
    text = _upload(factory, alice, blobs, text="an apple")
    with session_factory() as s:
        row = s.get(orm.Capture, text.id)
        assert row is not None
        row.kind = "audio"
        s.commit()
    with pytest.raises(Exception, match="no audio to transcribe"):
        uc.TranscribeCapture(factory, alice, blobs, fake).execute(text.id)

    voice = _upload(factory, alice, blobs, data=b"OggS-voice", filename="v.oga", mime="audio/ogg")
    blobs.blobs.clear()
    with pytest.raises(NotFound, match="missing"):
        uc.TranscribeCapture(factory, alice, blobs, fake).execute(voice.id)


def test_t_svc_436_body_profile_tolerates_bad_values() -> None:
    """T-SVC-436: no settings, an unknown sex and an unreadable birth date each come back as
    ``None`` for that field rather than an error."""
    assert body_uc.body_profile(_settings_uow(None)) == (None, None, None)
    profile = body_uc.body_profile(
        _settings_uow({"body": {"height_cm": 180, "sex": "other", "birth_date": "1990-13-40"}})
    )
    assert profile == (180.0, None, None)


def test_t_svc_437_rule_limit(
    factory: UowFactory, alice: TenantContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-SVC-437: past the rule limit a new rule is 409, while an existing one may still be
    replaced."""
    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    monkeypatch.setattr(rules_uc, "MAX_RULES", 2)
    for when in ("oats", "rye"):
        rules_uc.UpsertRule(factory, alice).execute(rules_uc.RuleInput(when=when, then="weigh it"))
    with pytest.raises(Conflict, match="at most 2 rules"):
        rules_uc.UpsertRule(factory, alice).execute(rules_uc.RuleInput(when="tea", then="x"))
    replaced = rules_uc.UpsertRule(factory, alice).execute(
        rules_uc.RuleInput(when="oats", then="ask")
    )
    assert replaced.then == "ask"


def test_t_svc_438_a_failed_assessment_is_recorded(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-438: marking a snapshot failed stores the (shortened) error; an unknown one is
    404."""
    snap = snapshots_uc.FreezeReport(factory, alice).execute(
        "checkup",
        "Am I on track?",
        {"title": "t", "blocks": []},
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 14),
        today=date(2026, 1, 14),
    )
    failed = snapshots_uc.MarkSnapshotFailed(factory, alice).execute(snap.id, "x" * 3000)
    assert failed.status == "failed"
    full = snapshots_uc.GetSnapshot(factory, alice).execute(snap.id)
    assert full.assessment_md is not None and len(full.assessment_md) == 2000
    with pytest.raises(NotFound):
        snapshots_uc.MarkSnapshotFailed(factory, alice).execute("snap_none", "boom")


def test_t_svc_453_a_second_measurement_at_the_same_moment_is_refused(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-453: two body measurements with one timestamp are a conflict (409), and a body
    fat percentage outside 3–70 is refused."""
    at = datetime(2026, 3, 1, 7, 0, tzinfo=UTC)
    body_uc.AddBodyMeasurement(factory, alice).execute(
        body_uc.BodyInput(measured_at=at, waist_cm=90)
    )
    with pytest.raises(Conflict, match="timestamp"):
        body_uc.AddBodyMeasurement(factory, alice).execute(
            body_uc.BodyInput(measured_at=at, hip_cm=100)
        )
    with pytest.raises(ValidationFailed, match="body fat"):
        body_uc.AddBodyMeasurement(factory, alice).execute(
            body_uc.BodyInput(measured_at=at + timedelta(days=1), body_fat_pct=80)
        )
