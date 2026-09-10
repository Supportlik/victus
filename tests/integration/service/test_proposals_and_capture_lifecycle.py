"""T-SVC-050…066, T-SVC-090: product proposals, capture lifecycle, retention, echo guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import captures as uc
from victus.application.use_cases import day_logs as days_uc
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


def test_processed_captures_and_their_files_go_after_the_retention(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-066: processed captures are cleaned up with their blobs (R66)."""
    from victus.application.schemas_loader import load_schema
    from victus.application.use_cases import settings as settings_uc

    blobs = InMemoryBlobStorage()
    cap = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(data=PNG, filename="plate.png", mime="image/png")
    )
    view = uc.GetCapture(factory, alice).execute(cap.id)
    key = next(iter(blobs.blobs))
    with factory(alice) as uow:
        row = uow.captures.get(cap.id)
        assert row is not None
        row.status = "processed"
        row.processed_at = datetime.now(UTC) - timedelta(days=11)
        uow.commit()

    # the default retention is ten days, so an eleven day old capture is due
    assert view.attachments
    assert all(c.id != cap.id for c in uc.ListCaptures(factory, alice, blobs).execute())
    assert key not in blobs.blobs

    # with the retention turned off a processed capture stays, files and all
    data = dict(load_schema("tenant-settings")["examples"][0])
    data["captures"] = {"processed_retention_days": 0}
    settings_uc.PutSettings(factory, alice).execute(data)
    kept = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(data=PNG + b"tail", filename="other.png", mime="image/png")
    )
    with factory(alice) as uow:
        row = uow.captures.get(kept.id)
        assert row is not None
        row.status = "processed"
        row.processed_at = datetime.now(UTC) - timedelta(days=400)
        uow.commit()
    assert any(c.id == kept.id for c in uc.ListCaptures(factory, alice, blobs).execute())


def test_prompt_echo_transcripts_mark_the_capture_failed(
    factory: UowFactory, alice: TenantContext
) -> None:
    vocab = "Krafttraining: Hackenschmidt, Hack Squat, Sumo Deadlift"
    assert looks_like_prompt_echo("", vocab)
    assert looks_like_prompt_echo("Hackenschmidt Hack Squat", vocab)
    assert not looks_like_prompt_echo("heute Mittag 300 g Hähnchen und Reis", vocab)

    # T-SVC-054: what a silent recording actually returned — the whole prompt. The rule
    # stopped looking above forty words, so the one case it exists for went through and
    # a three-second recording was stored as seventy words of exercise and food names.
    long_vocab = (
        "Krafttraining nach GZCLP: Hackenschmidt, Hack Squat, Sumo Deadlift, Romanian "
        "Deadlift, Lat Pulldown, Shoulder Press, Flat Bench Press, Incline Bench, Chest "
        "Flyes, Lateral Raises, Hip Thrusts, Seated Row, Bent Over Row, Ab Machine, "
        "Assisted Pullup, AMRAP, T1, T2, T3, Satz, Wiederholungen, Kilogramm. "
        "Ernährung: Skyr, Haferflocken, Chiasamen, Magerquark, Proteinshake, "
        "Kaisergemüse, Kokosmilch, Soba, Rinderhack, Kalorien, Eiweiß, Ballaststoffe."
    )
    assert looks_like_prompt_echo(long_vocab, long_vocab)
    # and the same prompt with a few real words in front no longer dilutes its way past
    # the ratio: a run of the prompt in the prompt's own order is an echo either way
    assert looks_like_prompt_echo(
        "ich habe heute nichts gesagt aber hier kommt es trotzdem " + long_vocab, long_vocab
    )
    # a long genuine note stays a note, even when it names things from the list
    note = (
        "Zum Frühstück hatte ich Skyr mit Haferflocken und Beeren, dazu einen Kaffee. "
        "Mittags gab es Rinderhack mit Reis und Kaisergemüse, ungefähr 400 Gramm, und "
        "abends nur zwei Scheiben Brot mit Käse, weil ich keinen Hunger mehr hatte."
    )
    assert not looks_like_prompt_echo(note, long_vocab)
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


def test_t_svc_090_usage_of_a_pending_one_off_names_the_day_and_meal(
    factory: UowFactory, alice: TenantContext
) -> None:
    """A ``new`` proposal has no product to look at, but its values were already eaten."""
    pr = prop_uc.ProposeNewProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Protein bar", kcal=380, protein=30, carbs=28, fat=14, fiber=6, salt=1
        ),
        rationale="read from the wrapper",
    )
    assert pr.consumable_id is not None
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = days_uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    for _ in range(2):
        days_uc.AddLineItem(factory, alice).execute(
            meal.id,
            days_uc.LineItemInput(consumable_id=pr.consumable_id, amount=60, unit_code="g"),
        )

    # the one-off answers the product usage question, which is what makes the proposal
    # decidable: this is the day, this is the meal, this is how much
    usage = products_uc.GetProductUsage(factory, alice).execute(pr.consumable_id, limit=1)
    assert [(e.date, e.meal, e.base_amount) for e in usage.entries] == [(DAY, "Breakfast", 60)]
    # asking for one entry still says how many there are, so a list can print the number
    assert usage.item_count == 2
