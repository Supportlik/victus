"""T-SVC-481…485: the agent's search, one-offs that come back, and the catalogue vocabulary (#78).

Every name here is synthetic: "Bakery Valdrik", "Brand Y", "Brand Z" stand for whatever a
person's catalogue holds.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from tests.integration.service.conftest import DAY
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import products as uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.infrastructure.transcription.fake import FakeTranscription

pytestmark = pytest.mark.service

BREAD = "Bakery Valdrik Fitnessbrötchen (wheat 95 % / rye 5 %, with quark)"
CATALOGUE: list[dict[str, Any]] = [
    {"name": BREAD, "kcal": 290},
    {"name": "Bakery Valdrik rye bread", "kcal": 230},
    {"name": "Brötchen (plain wheat roll)", "kcal": 270},
    {"name": "Fitness muesli", "kcal": 360},
    {"name": "Cheese slices (light)", "brand": "Brand Y", "kcal": 270},
    {"name": "Cheese slices (medium)", "brand": "Brand Q", "kcal": 300},
    {"name": "Cheddar block", "brand": "Brand Y", "kcal": 400},
    {"name": "Frozen lasagne", "brand": "Brand W", "kcal": 150, "ean": "2001234500018"},
]


def _seed(factory: UowFactory, ctx: TenantContext) -> dict[str, int]:
    made: dict[str, int] = {}
    for row in CATALOGUE:
        view = uc.CreateProduct(factory, ctx).execute(uc.ProductInput(**row))
        made[f"{row['name']}|{row.get('brand') or ''}"] = view.id
    return made


def _found(factory: UowFactory, ctx: TenantContext, q: str, **kw: Any) -> list[tuple[str, int]]:
    view = uc.FindProducts(factory, ctx).execute(q, **kw)
    return [(f.kind, (f.product or f.ad_hoc).id) for f in view.items]  # type: ignore[union-attr]


def test_t_svc_481_a_verbatim_transcript_phrase_finds_the_intended_product(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-481: the phrase as a transcript has it — quantity, filler words, a misheard
    bakery — ranks the long catalogue name first, where the field search finds nothing;
    the cheese comes first for its brand; a barcode finds the product that carries it."""
    made = _seed(factory, alice)
    phrase = "110 g Fitnessbrötchen from Bakery Waldrik"

    assert uc.SearchProducts(factory, alice).execute(phrase) == [], "the field search: nothing"
    found = uc.FindProducts(factory, alice).execute(phrase)
    assert found.items[0].product is not None and found.items[0].product.name == BREAD
    assert found.items[0].matched_by == ["fitnessbroetchen", "bakery", "waldrik"]
    assert found.items[0].score > found.items[1].score
    assert found.variants[:2] == [phrase, "fitnessbroetchen bakery waldrik"]

    cheese = _found(factory, alice, "6 slices of Brand Y cheese (thin slices)")
    assert cheese[0] == ("product", made["Cheese slices (light)|Brand Y"])
    assert ("product", made["Cheese slices (medium)|Brand Q"]) in cheese[1:]

    meal = uc.FindProducts(factory, alice).execute("2001234500018")
    assert meal.items[0].matched_by == ["ean"] and meal.items[0].score == 1.0
    assert meal.items[0].product is not None and meal.items[0].product.ean == "2001234500018"
    assert _found(factory, alice, "110 g") == [], "nothing but an amount finds nothing"


def test_t_svc_482_one_offs_are_found_marked_and_below_a_product(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    """T-SVC-482: a one-off is returned as `ad_hoc` with its values; it ranks below a product
    that fits as well; the same food estimated twice comes back once (the newest); another
    tenant's one-off is not seen; a product with versions shows the one valid on the day."""
    with factory(alice) as uow:
        older = uow.products.add_ad_hoc_item("Butter chicken (Brand Z)", kcal=140.0)
        newer = uow.products.add_ad_hoc_item("butter chicken (brand z)", kcal=150.0)
        uow.products.add_ad_hoc_item("Chicken curry", kcal=120.0, reference_amount=200.0)
        uow.commit()
        older_id, newer_id = older.id, newer.id
    with factory(bob) as uow:
        uow.products.add_ad_hoc_item("Butter chicken (Brand Z)", kcal=999.0)
        uow.commit()
    product = uc.CreateProduct(factory, alice).execute(
        uc.ProductInput(name="Chicken curry", kcal=130)
    )

    view = uc.FindProducts(factory, alice).execute("1 pack Brand Z butter chicken")
    assert _found(factory, alice, "1 pack Brand Z butter chicken")[0] == ("ad_hoc", newer_id)
    one_off = view.items[0].ad_hoc
    assert one_off is not None and one_off.kcal == 150.0
    assert older_id not in [f.ad_hoc.id for f in view.items if f.ad_hoc is not None]

    curry = uc.FindProducts(factory, alice).execute("Chicken curry")
    assert [f.kind for f in curry.items][:2] == ["product", "ad_hoc"]
    assert curry.items[0].product is not None and curry.items[0].product.id == product.id
    assert curry.items[1].score < curry.items[0].score

    replaced = uc.NewProductVersion(factory, alice).execute(product.id, DAY, {"kcal": 135})
    before = uc.FindProducts(factory, alice).execute("Chicken curry", on=DAY - timedelta(days=1))
    after = uc.FindProducts(factory, alice).execute("Chicken curry", on=DAY)
    assert before.items[0].product is not None and before.items[0].product.id == product.id
    assert after.items[0].product is not None and after.items[0].product.id == replaced.id
    assert [f.kind for f in after.items].count("product") == 1, "one row per version chain"
    assert len(uc.FindProducts(factory, alice).execute("chicken", limit=1).items) == 1
    with factory(alice) as uow:
        first = uow.products.get(product.id)
        assert first is not None
        first.valid_from = DAY - timedelta(days=10)
        uow.commit()
    too_early = uc.FindProducts(factory, alice).execute(
        "Chicken curry", on=DAY - timedelta(days=20)
    )
    assert [f.kind for f in too_early.items].count("product") == 0, "no version on that day"


def _begin(factory: UowFactory, ctx: TenantContext, day: date) -> str:
    capture_uc.UploadCapture(factory, ctx, InMemoryBlobStorage()).execute(
        capture_uc.UploadInput(text=f"lunch on {day.isoformat()}", target_date=day)
    )
    return agent_uc.BeginAgentRun(factory, ctx).execute(runner="external", dates=[day]).run.id


def _one_off_item(raw: str, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "raw_text": raw,
        "candidates": [],
        "chosen_consumable_id": None,
        "one_off_nutrition_per_100": {"kcal": 150, "protein": 12, "source": "estimate"},
        "quantity": 400,
        "unit_code": "g",
        "estimated": True,
        "quantity_estimated": False,
        "confidence": 0.6,
        "rationale": "no catalogue entry",
        "source_kind": "text",
        "source_capture_id": "cap_test",
    }
    item.update(over)
    return item


def _draft(
    factory: UowFactory, ctx: TenantContext, day: date, *items: dict[str, Any]
) -> agent_uc.dto.DraftCreateView:
    run_id = _begin(factory, ctx, day)
    view = agent_uc.CreateDraft(factory, ctx).execute(
        {
            "run_id": run_id,
            "date": day.isoformat(),
            "source_captures": [],
            "meals": [{"name": "Lunch", "line_items": list(items)}],
        }
    )
    agent_uc.FinishAgentRun(factory, ctx).execute(run_id)
    return view


def _item_ids(factory: UowFactory, ctx: TenantContext, day: date) -> list[int]:
    view = day_uc.GetDay(factory, ctx).execute(day)
    return [li.consumable_id for m in view.meals for li in m.line_items]


def test_t_svc_483_a_one_off_comes_back_and_is_proposed_once(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-483: a one-off is named after the food; on a later day `product_search` returns
    it; logged again, the draft reuses it and files exactly one `new` proposal, a third time
    none; approving promotes it in place, keeping its id and both line items."""
    first = _draft(factory, alice, DAY, _one_off_item("1 pack Brand Z butter chicken"))
    assert first.created_ad_hoc == 1 and first.proposed_products == []
    (one_off_id,) = _item_ids(factory, alice, DAY)
    with factory(alice) as uow:
        consumable = uow.products.get_consumable(one_off_id)
        assert consumable is not None and consumable.name == "Brand Z butter chicken"

    later = DAY + timedelta(days=3)
    found = uc.FindProducts(factory, alice).execute("butter chicken", on=later)
    assert [(f.kind, f.ad_hoc.id) for f in found.items if f.ad_hoc] == [("ad_hoc", one_off_id)]

    # the second time, named by the agent as the food, in other words than the first raw text
    second = _draft(
        factory,
        alice,
        later,
        _one_off_item(
            "and that butter chicken again", one_off_name="brand z Butter Chicken", quantity=350
        ),
    )
    assert _item_ids(factory, alice, later) == [one_off_id], "logged against the same one-off"
    assert second.proposed_products == ["Brand Z butter chicken"]
    pending = prop_uc.ListProposals(factory, alice).execute(consumable_id=one_off_id)
    assert [(p.kind, p.status) for p in pending] == [("new", "pending")]
    assert pending[0].changes["kcal"] == 150 and pending[0].changes["reference_unit"] == "g"

    third_day = later + timedelta(days=1)
    third = _draft(
        factory,
        alice,
        third_day,
        _one_off_item("Brand Z butter chicken", chosen_consumable_id=one_off_id),
    )
    assert third.proposed_products == []
    assert len(prop_uc.ListProposals(factory, alice).execute(status=None)) == 1

    decided = prop_uc.DecideProposal(factory, alice).execute(pending[0].id, approve=True)
    assert decided.product_id == one_off_id, "promoted in place: the id stays"
    for day in (DAY, later, third_day):
        assert _item_ids(factory, alice, day) == [one_off_id]
    product = uc.GetProduct(factory, alice).execute(one_off_id)
    assert product.name == "Brand Z butter chicken" and product.kcal == 150


def test_t_svc_484_no_proposal_where_a_person_was_asked_or_it_would_collide(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-484: a one-off whose proposal was rejected is not filed again; one named like a
    catalogue product is not filed; a one-off in another unit is a new one-off; the same
    food twice in one draft files its proposal there; a product never gets one."""
    _draft(factory, alice, DAY, _one_off_item("Lentil soup"))
    (soup,) = _item_ids(factory, alice, DAY)
    filed = _draft(factory, alice, DAY + timedelta(days=1), _one_off_item("lentil soup"))
    assert filed.proposed_products == ["Lentil soup"]
    (proposal,) = prop_uc.ListProposals(factory, alice).execute(consumable_id=soup)
    prop_uc.DecideProposal(factory, alice).execute(proposal.id, approve=False)
    again = _draft(factory, alice, DAY + timedelta(days=2), _one_off_item("Lentil soup"))
    assert again.proposed_products == [] and _item_ids(factory, alice, DAY + timedelta(days=2)) == [
        soup
    ]

    # in millilitres it cannot share the gram-based one-off
    drink = _draft(
        factory, alice, DAY + timedelta(days=3), _one_off_item("lentil soup", unit_code="ml")
    )
    (other,) = _item_ids(factory, alice, DAY + timedelta(days=3))
    assert other != soup and drink.created_ad_hoc == 1

    with factory(alice) as uow:
        clash = uow.products.add_ad_hoc_item("Skyr natural", kcal=60.0)
        plain = uow.products.add_ad_hoc_item("Rice cakes", kcal=380.0)  # no source given
        uow.commit()
        clash_id, plain_id = clash.id, plain.id
    day = DAY + timedelta(days=4)
    twice = _draft(
        factory,
        alice,
        day,
        _one_off_item("Oat porridge"),
        _one_off_item("oat porridge, second bowl", one_off_name="oat porridge"),
        _one_off_item("skyr", chosen_consumable_id=clash_id),
        _one_off_item("skyr", chosen_consumable_id=clash_id),
        _one_off_item("skyr", chosen_consumable_id=skyr, unit_code="tub", quantity=1),
        _one_off_item("rice cakes", chosen_consumable_id=plain_id, quantity=20),
        _one_off_item("rice cakes", chosen_consumable_id=plain_id, quantity=20),
    )
    assert twice.proposed_products == ["Oat porridge", "Rice cakes"], (
        "a name the catalogue has is not filed"
    )
    (rice,) = prop_uc.ListProposals(factory, alice).execute(consumable_id=plain_id)
    assert rice.source is None and "source" not in rice.changes


def test_t_svc_485_the_catalogue_teaches_the_transcription_its_words(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-485: the vocabulary prompt gets the catalogue's brands (most logged first) and
    most logged product names without their details, skipping what the tenant's prompt
    has and stopping at the limit; a note made of catalogue words is not an echo, the
    catalogue read back in its own order is."""
    from victus.application.use_cases import settings as settings_uc

    made = _seed(factory, alice)
    from tests.integration.agent.test_cov_runner import SETTINGS

    settings_uc.PutSettings(factory, alice).execute(
        {**SETTINGS, "transcription": {"language": "en", "vocabulary_prompt": "skyr, Brand W"}}
    )
    day_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    for _ in range(2):
        day_uc.AddLineItemOnDate(factory, alice).execute(
            DAY,
            "Lunch",
            day_uc.LineItemInput(consumable_id=made[f"{BREAD}|"], amount=110, unit_code="g"),
        )
    day_uc.AddLineItemOnDate(factory, alice).execute(
        DAY,
        "Lunch",
        day_uc.LineItemInput(
            consumable_id=made["Cheese slices (light)|Brand Y"], amount=60, unit_code="g"
        ),
    )
    with factory(alice) as uow:
        words = capture_uc.catalogue_vocabulary(uow, 40, "skyr, Brand W")
        assert words == ("Brand Y, Brand Q, Bakery Valdrik Fitnessbrötchen, Cheese slices"), (
            "brands first, then names without details; Brand W is in the prompt already"
        )
        assert capture_uc.catalogue_vocabulary(uow, 2, None) == "Brand Y, Brand Q"
        assert capture_uc.catalogue_vocabulary(uow, 0, None) == ""

    blobs = InMemoryBlobStorage()
    cap = capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(
            data=b"RIFF....WAVEfake", filename="note.wav", mime="audio/wav", target_date=DAY
        )
    )
    speech = FakeTranscription("Brand Y cheese slices")
    view = capture_uc.TranscribeCapture(factory, alice, blobs, speech, catalogue_terms=40).execute(
        cap.id
    )
    sent = speech.calls[-1]["vocabulary_prompt"]
    assert sent.startswith("skyr, Brand W, Brand Y") and "Bakery Valdrik Fitnessbrötchen" in sent
    assert view.transcript == "Brand Y cheese slices", "a note of catalogue words is speech"

    assert capture_uc.looks_like_prompt_echo(sent, "skyr, Brand W", words), "the prompt read back"
    assert not capture_uc.looks_like_prompt_echo("Brand Y cheese slices", None, words)
