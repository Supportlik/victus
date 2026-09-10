"""Capture use cases (SPEC R35, R36, R51) against an in-memory database."""

from __future__ import annotations

from datetime import date

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import ExternalServiceError, NotFound, ValidationFailed
from victus.application.ports.transcription import TranscriptionResult
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as uc
from victus.application.use_cases import day_logs as days_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db import orm
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
    # every answer lists the files: a view without them told the card the photos were gone
    assert len(view.attachments) == 3
    assert len(uc.TranscribeCapture(factory, alice, blobs, fake).execute(cap.id).attachments) == 3
    moved = uc.UpdateCapture(factory, alice).execute(cap.id, {"target_date": DAY})
    assert len(moved.attachments) == 3

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


class NumberedTranscription:
    """A provider that answers every recording differently.

    ``FakeTranscription`` returns one text however often it is called, which cannot show
    which transcript came from which file.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        filename: str | None = None,
        language: str | None = None,
        vocabulary_prompt: str | None = None,
    ) -> TranscriptionResult:
        self.calls.append((mime, filename))
        n = len(self.calls)
        return TranscriptionResult(
            text=f"note {n}",
            provider="fake",
            model="fake-1",
            language=language,
            duration_s=10.0 * n,
            segments=None,
            cost_usd=0.0,
        )


def test_the_day_thread_carries_every_spoken_note(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    """T-SVC-087: a capture of two recordings reaches the thread with both texts.

    Each recording has its own transcript, but the thread asked for the newest single one,
    so the first note never reached a thread message — nor the day context the drafting
    prompt is built on, which is the one place a dropped sentence turns into a missing
    meal.
    """
    provider = NumberedTranscription()
    cap = _upload(
        factory,
        alice,
        blobs,
        data=b"OggS-one",
        filename="one.webm",
        mime="audio/webm",
        target_date=DAY,
        files=(uc.UploadFile(b"OggS-two", "two.webm", "audio/webm"),),
    )
    uc.TranscribeCapture(factory, alice, blobs, provider).execute(cap.id)

    thread = days_uc.GetDayThread(factory, alice).execute(DAY)
    entry = next(m for m in thread if m.capture_id == cap.id)
    assert entry.transcript == "note 1\nnote 2", "both notes, in the order they were recorded"

    context = agent_uc.GetDayContext(factory, alice).execute(DAY)
    assert "note 1" in str(context) and "note 2" in str(context)


def test_two_voice_notes_each_get_their_own_transcript(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    """T-SVC-081: every recording is transcribed, and its text says which one it is.

    Two spoken notes in one capture is ordinary (R65). Only the first was ever sent to a
    provider, so the second was stored, played and never read — and the one transcript
    was printed under both players, telling the reader neither which recording it came
    from nor that another had never been listened to.
    """
    provider = NumberedTranscription()
    cap = _upload(
        factory,
        alice,
        blobs,
        data=b"OggS-first-note",
        filename="note-1.webm",
        mime="audio/webm",
        files=(
            uc.UploadFile(b"\xff\xd8\xff-fake-jpeg", "photo.jpg", "image/jpeg"),
            uc.UploadFile(b"OggS-second-note", "note-2.webm", "audio/webm"),
        ),
    )
    view = uc.TranscribeCapture(factory, alice, blobs, provider).execute(cap.id)

    # the photo between the two notes never reaches ffmpeg
    assert provider.calls == [("audio/webm", "note-1.webm"), ("audio/webm", "note-2.webm")]
    recordings = [a.id for a in view.attachments if a.mime.startswith("audio/")]
    assert [(t.attachment_id, t.text, t.duration_s) for t in view.transcripts] == [
        (recordings[0], "note 1", 10.0),
        (recordings[1], "note 2", 20.0),
    ]
    # one field for a reader of one field: nothing is dropped from it
    assert view.transcript == "note 1\nnote 2"

    # both are stored, so a second call asks the provider for nothing
    uc.TranscribeCapture(factory, alice, blobs, provider).execute(cap.id)
    assert len(provider.calls) == 2
    again = uc.TranscribeCapture(factory, alice, blobs, provider).execute(cap.id, force=True)
    assert len(provider.calls) == 4
    assert [t.text for t in again.transcripts] == ["note 3", "note 4"]
    assert [t.attachment_id for t in again.transcripts] == recordings


def test_a_transcript_without_a_recording_belongs_to_the_first_one(
    factory: UowFactory, alice: TenantContext, blobs: InMemoryBlobStorage
) -> None:
    """T-SVC-082: rows written before transcripts knew their recording still show up.

    ``attachment_id`` is nullable for them. Only the first recording was ever sent, so
    that is the one such a row describes, and the second must still say it is waiting.
    """
    cap = _upload(
        factory,
        alice,
        blobs,
        data=b"OggS-first-note",
        filename="old-1.webm",
        mime="audio/webm",
        files=(uc.UploadFile(b"OggS-second-note", "old-2.webm", "audio/webm"),),
    )
    with factory(alice) as uow:
        uow.captures.add_transcript(
            orm.Transcript(
                capture_id=cap.id,
                provider="openai",
                model="gpt-4o-transcribe",
                text="what the first note said",
                duration_s=42.0,
            )
        )
        uow.commit()

    view = uc.GetCapture(factory, alice).execute(cap.id)
    first, second = (a.id for a in view.attachments)
    assert [(t.attachment_id, t.text) for t in view.transcripts] == [
        (first, "what the first note said")
    ]
    assert second not in {t.attachment_id for t in view.transcripts}

    # transcribing now leaves the attributed one alone and reads the one that was never read
    provider = NumberedTranscription()
    done = uc.TranscribeCapture(factory, alice, blobs, provider).execute(cap.id)
    assert provider.calls == [("audio/webm", "old-2.webm")]
    assert [(t.attachment_id, t.text) for t in done.transcripts] == [
        (first, "what the first note said"),
        (second, "note 1"),
    ]


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
