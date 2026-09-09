"""Capture use cases (SPEC R35, R36, R51) against an in-memory database."""

from __future__ import annotations

from datetime import date

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import ExternalServiceError, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as uc
from victus.application.use_cases import day_logs as days_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription

pytestmark = pytest.mark.service

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture
def blobs() -> InMemoryBlobStorage:
    return InMemoryBlobStorage()


def _upload(factory: UowFactory, ctx: TenantContext, blobs: InMemoryBlobStorage, **kw: object):  # type: ignore[no-untyped-def]
    return uc.UploadCapture(factory, ctx, blobs).execute(uc.UploadInput(**kw))  # type: ignore[arg-type]


def test_text_capture_is_deduplicated_by_hash(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    first = _upload(factory, alice, blobs, text="lunch: 400 g quark")
    second = _upload(factory, alice, blobs, text="  lunch: 400 g quark ")
    assert first.created is True and first.kind == "text" and first.status == "new"
    assert second.created is False and second.id == first.id
    assert len(uc.ListCaptures(factory, alice).execute()) == 1


def test_attachment_kind_is_sniffed_from_extension(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    voice = _upload(
        factory,
        alice,
        blobs,
        data=b"OggS-fake-audio",
        filename="note.oga",
        mime="application/octet-stream",
    )
    assert voice.kind == "audio" and voice.attachment_mime == "audio/ogg"
    photo = _upload(factory, alice, blobs, data=PNG, filename="label.png", mime="image/png")
    assert photo.kind == "image" and photo.attachment_id is not None
    assert blobs.exists(next(iter(blobs.blobs)))
    with pytest.raises(ValidationFailed):
        _upload(factory, alice, blobs, data=b"%PDF-1.7", filename="x.pdf", mime="application/pdf")
    with pytest.raises(ValidationFailed):
        _upload(factory, alice, blobs)


def test_same_file_twice_reuses_the_attachment(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    a = _upload(factory, alice, blobs, data=PNG, filename="a.png", mime="image/png")
    b = _upload(factory, alice, blobs, data=PNG, filename="b.png", mime="image/png")
    assert b.created is False and b.attachment_id == a.attachment_id
    assert len(blobs.blobs) == 1


def test_attachment_download_and_tenant_isolation(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    photo = _upload(factory, alice, blobs, data=PNG, filename="label.png", mime="image/png")
    assert photo.attachment_id is not None
    content = uc.GetAttachment(factory, alice, blobs).execute(photo.attachment_id)
    assert content.data == PNG and content.mime == "image/png"
    with pytest.raises(NotFound):
        uc.GetAttachment(factory, bob, blobs).execute(photo.attachment_id)
    with pytest.raises(NotFound):
        uc.GetCapture(factory, bob).execute(photo.id)
    assert uc.ListCaptures(factory, bob).execute() == []


def test_message_on_drafted_day_queues_exactly_one_follow_up(
    factory: UowFactory, alice: TenantContext, skyr: int, blobs: InMemoryBlobStorage
) -> None:
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = days_uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    days_uc.AddLineItem(factory, alice).execute(
        meal.id,
        days_uc.LineItemInput(consumable_id=skyr, amount=400, unit_code="g"),
        origin="agent",
        is_draft=True,
    )
    # a plain capture with target_date and a day-thread message both count
    cap = _upload(factory, alice, blobs, text="the skyr was only half a tub", target_date=DAY)
    days_uc.AddDayMessage(factory, alice).execute(DAY, "and I had an apple")
    runs = agent_uc.ListAgentRuns(factory, alice).execute()
    follow_ups = [r for r in runs if r.mode == "follow_up"]
    assert len(follow_ups) == 1
    assert follow_ups[0].status == "queued" and follow_ups[0].days == [DAY]
    assert cap.id in follow_ups[0].captures and len(follow_ups[0].captures) == 2
    # a day without draft or lock queues nothing
    _upload(factory, alice, blobs, text="breakfast", target_date=date(2026, 3, 11))
    assert len([r for r in agent_uc.ListAgentRuns(factory, alice).execute()]) == 1


def test_update_capture_status_and_target_date(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    cap = _upload(factory, alice, blobs, text="something")
    moved = uc.UpdateCapture(factory, alice).execute(cap.id, {"target_date": DAY})
    assert moved.target_date == DAY
    discarded = uc.UpdateCapture(factory, alice).execute(cap.id, {"status": "discarded"})
    assert discarded.status == "discarded" and discarded.processed_at is not None
    with pytest.raises(ValidationFailed):
        uc.UpdateCapture(factory, alice).execute(cap.id, {"status": "bogus"})
    assert [c.id for c in uc.ListCaptures(factory, alice).execute(status="discarded")] == [cap.id]


def test_transcription_stores_transcript_and_uses_tenant_vocabulary(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    from victus.application.schemas_loader import load_schema
    from victus.application.use_cases import settings as settings_uc

    data = dict(load_schema("tenant-settings")["examples"][0])
    data["transcription"] = {"language": "en", "vocabulary_prompt": "skyr, quark"}
    settings_uc.PutSettings(factory, alice).execute(data)
    fake = FakeTranscription("four hundred grams of skyr")
    cap = _upload(
        factory, alice, blobs, data=b"RIFF-fake-wav", filename="note.wav", mime="audio/wav"
    )
    view = uc.TranscribeCapture(factory, alice, blobs, fake).execute(cap.id)
    assert view.transcript == "four hundred grams of skyr"
    assert fake.calls[0]["language"] == "en"
    assert fake.calls[0]["vocabulary_prompt"] == "skyr, quark"
    # cached: a second call without force does not hit the provider
    uc.TranscribeCapture(factory, alice, blobs, fake).execute(cap.id)
    assert len(fake.calls) == 1
    uc.TranscribeCapture(factory, alice, blobs, fake).execute(cap.id, force=True)
    assert len(fake.calls) == 2
    assert uc.GetCapture(factory, alice).execute(cap.id).transcript == "four hundred grams of skyr"


def test_the_voice_note_is_transcribed_not_the_photo_beside_it(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    """A capture is one thing with several parts, and the parts arrive in any order.

    Two photos and a spoken note is an ordinary capture (R65). Transcription used to take
    the part that arrived first, so a photo went to ffmpeg, which produced an mp3 with no
    stream in it and reported it as a conversion failure.
    """
    fake = FakeTranscription("frosta bag, five hundred grams")
    cap = _upload(
        factory,
        alice,
        blobs,
        data=b"\xff\xd8\xff-fake-jpeg",
        filename="photo-1.jpg",
        mime="image/jpeg",
        files=(
            uc.UploadFile(b"\xff\xd8\xff-second-jpeg", "photo-2.jpg", "image/jpeg"),
            uc.UploadFile(b"OggS-fake-audio", "voice.webm", "audio/webm"),
        ),
    )
    assert cap.kind == "audio", "a capture with audio in it is an audio capture"

    view = uc.TranscribeCapture(factory, alice, blobs, fake).execute(cap.id)
    assert view.transcript == "frosta bag, five hundred grams"
    assert fake.calls[0]["mime"] == "audio/webm"

    # a capture that is only photos says so instead of failing in the converter
    photos = _upload(
        factory,
        alice,
        blobs,
        data=b"\xff\xd8\xff-only-a-photo",
        filename="label.jpg",
        mime="image/jpeg",
    )
    with pytest.raises(ValidationFailed):
        uc.TranscribeCapture(factory, alice, blobs, fake).execute(photos.id)


def test_transcription_failure_marks_capture_failed(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    cap = _upload(
        factory, alice, blobs, data=b"RIFF-fake-wav", filename="note.wav", mime="audio/wav"
    )
    with pytest.raises(ExternalServiceError):
        uc.TranscribeCapture(factory, alice, blobs, FakeTranscription(fail=True)).execute(cap.id)
    assert uc.GetCapture(factory, alice).execute(cap.id).status == "failed"
    # a later success clears the failure
    ok = uc.TranscribeCapture(factory, alice, blobs, FakeTranscription("ok")).execute(cap.id)
    assert ok.status == "new" and ok.transcript == "ok"
    with pytest.raises(ExternalServiceError):
        uc.TranscribeCapture(factory, alice, blobs, None).execute(cap.id, force=True)
    text_cap = _upload(factory, alice, blobs, text="not audio")
    with pytest.raises(ValidationFailed):
        uc.TranscribeCapture(factory, alice, blobs, FakeTranscription()).execute(text_cap.id)
