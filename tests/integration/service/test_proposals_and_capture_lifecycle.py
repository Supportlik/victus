"""T-SVC-050…055: product proposals, capture delete/purge, transcript echo guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import captures as uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.application.use_cases.captures import looks_like_prompt_echo
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def _label_capture(
    factory: UowFactory, alice: TenantContext, skyr: int, blobs: InMemoryBlobStorage
):  # type: ignore[no-untyped-def]
    return uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(data=PNG, filename="label.png", mime="image/png", product_id=skyr)
    )


def test_proposal_approve_applies_and_verifies(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    blobs = InMemoryBlobStorage()
    cap = _label_capture(factory, alice, skyr, blobs)
    pr = prop_uc.ProposeProductChange(factory, alice).execute(
        skyr,
        {"kcal": 66, "protein": 11.5},
        rationale="label",
        source="label photo",
        capture_id=cap.id,
    )
    assert pr.status == "pending" and pr.current["kcal"] == 63
    assert uc.GetCapture(factory, alice).execute(cap.id).status == "assigned"
    assert len(prop_uc.ListProposals(factory, alice).execute()) == 1
    decided = prop_uc.DecideProposal(factory, alice).execute(
        pr.id, approve=True, changes={"protein": 11.6}
    )
    assert decided.status == "approved"
    p = products_uc.GetProduct(factory, alice).execute(skyr)
    assert p.kcal == 66 and p.protein == 11.6 and p.verified is True and p.source == "label photo"
    assert uc.GetCapture(factory, alice).execute(cap.id).status == "processed"
    with pytest.raises(Conflict):
        prop_uc.DecideProposal(factory, alice).execute(pr.id, approve=False)


def test_proposal_reject_discards_capture_and_guards(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, skyr: int
) -> None:
    cap = _label_capture(factory, alice, skyr, InMemoryBlobStorage())
    with pytest.raises(ValidationFailed):
        prop_uc.ProposeProductChange(factory, alice).execute(skyr, {"category_id": 3})
    with pytest.raises(ValidationFailed):
        prop_uc.ProposeProductChange(factory, alice).execute(skyr, {})
    pr = prop_uc.ProposeProductChange(factory, alice).execute(
        skyr, {"salt": 0.2}, capture_id=cap.id
    )
    with pytest.raises(NotFound):
        prop_uc.DecideProposal(factory, bob).execute(pr.id, approve=True)
    rejected = prop_uc.DecideProposal(factory, alice).execute(pr.id, approve=False)
    assert rejected.status == "rejected"
    assert uc.GetCapture(factory, alice).execute(cap.id).status == "discarded"
    assert products_uc.GetProduct(factory, alice).execute(skyr).salt == 0.1


def test_delete_capture_removes_orphan_blob(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    blobs = InMemoryBlobStorage()
    cap = _label_capture(factory, alice, skyr, blobs)
    assert len(blobs.blobs) == 1
    uc.DeleteCapture(factory, alice, blobs).execute(cap.id)
    with pytest.raises(NotFound):
        uc.GetCapture(factory, alice).execute(cap.id)
    assert blobs.blobs == {}


def test_delete_refuses_assigned_capture(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = _label_capture(factory, alice, skyr, InMemoryBlobStorage())
    prop_uc.ProposeProductChange(factory, alice).execute(skyr, {"kcal": 1}, capture_id=cap.id)
    with pytest.raises(Conflict):
        uc.DeleteCapture(factory, alice).execute(cap.id)


def test_discarded_captures_are_purged_after_a_day(
    factory: UowFactory, alice: TenantContext
) -> None:
    blobs = InMemoryBlobStorage()
    cap = uc.UploadCapture(factory, alice, blobs).execute(uc.UploadInput(text="old note"))
    uc.UpdateCapture(factory, alice).execute(cap.id, {"status": "discarded"})
    # still there within the retention window
    assert any(c.id == cap.id for c in uc.ListCaptures(factory, alice, blobs).execute())
    with factory(alice) as uow:
        row = uow.captures.get(cap.id)
        assert row is not None
        row.processed_at = datetime.now(UTC) - timedelta(days=2)
        uow.commit()
    assert all(c.id != cap.id for c in uc.ListCaptures(factory, alice, blobs).execute())


def test_prompt_echo_transcripts_mark_the_capture_failed(
    factory: UowFactory, alice: TenantContext
) -> None:
    vocab = "Krafttraining: Hackenschmidt, Hack Squat, Sumo Deadlift"
    assert looks_like_prompt_echo("", vocab)
    assert looks_like_prompt_echo("Hackenschmidt Hack Squat", vocab)
    assert not looks_like_prompt_echo("heute Mittag 300 g Hähnchen und Reis", vocab)
    blobs = InMemoryBlobStorage()
    cap = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(data=b"RIFF....WAVEfmt silence", filename="v.wav", mime="audio/wav")
    )
    view = uc.TranscribeCapture(
        factory, alice, blobs, FakeTranscription("Hackenschmidt Hack Squat")
    ).execute(cap.id)
    # no vocabulary configured for the test tenant, so only the empty case is an echo here
    assert view.transcript == "Hackenschmidt Hack Squat"
    cap2 = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(data=b"RIFF....WAVEfmt silence2", filename="v2.wav", mime="audio/wav")
    )
    view2 = uc.TranscribeCapture(factory, alice, blobs, FakeTranscription("")).execute(cap2.id)
    assert view2.status == "failed" and view2.transcript == ""


def test_several_files_become_one_capture(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-065: photos and a voice note taken together stay one note (R64)."""
    blobs = InMemoryBlobStorage()
    view = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(
            text="lunch at the bakery",
            files=(
                uc.UploadFile(data=PNG, filename="a.png", mime="image/png"),
                uc.UploadFile(data=PNG + b"x", filename="b.png", mime="image/png"),
                uc.UploadFile(data=b"RIFF....WAVEfmt ", filename="note.wav", mime="audio/wav"),
            ),
        )
    )
    assert [a.original_name for a in view.attachments] == ["a.png", "b.png", "note.wav"]
    assert view.attachment_id == view.attachments[0].id
    assert view.kind == "audio"  # the audio decides: it is what gets transcribed
    assert len(blobs.blobs) == 3

    # the same three files plus the same text are the same capture
    again = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(
            text="lunch at the bakery",
            files=(
                uc.UploadFile(data=PNG, filename="a.png", mime="image/png"),
                uc.UploadFile(data=PNG + b"x", filename="b.png", mime="image/png"),
                uc.UploadFile(data=b"RIFF....WAVEfmt ", filename="note.wav", mime="audio/wav"),
            ),
        )
    )
    assert again.created is False and again.id == view.id

    # deleting it takes every blob that nothing else uses
    uc.DeleteCapture(factory, alice, blobs).execute(view.id)
    assert blobs.blobs == {}
