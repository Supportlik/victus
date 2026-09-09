"""Day-log, draft and thread use cases against an in-memory database."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import Conflict, Forbidden, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import day_logs as uc
from victus.application.use_cases import drafts as drafts_uc
from victus.application.use_cases import recipes as recipes_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases import weights as weights_uc
from victus.application.use_cases._base import UowFactory
from victus.domain.values import BandZone

pytestmark = pytest.mark.service

BANDS = {
    "target_bands": [
        {
            "name": "Rest day",
            "training_type": "rest",
            "valid_from": "2026-01-01",
            "protein": {"min": 105, "opt_min": 150, "opt_max": 185, "target": 165, "max": 200},
            "carbs": {"min": 120, "opt_min": 155, "opt_max": 200, "target": 180, "max": 230},
            "fat": {"min": 45, "opt_min": 55, "opt_max": 70, "target": 58, "max": 75},
            "fiber": {"min": 25, "opt_min": 32, "opt_max": 38, "target": 35, "max": 50},
            "salt": {"min": 4, "opt_min": 6, "opt_max": 8, "target": 7, "max": 15},
        }
    ]
}


def _day_with_skyr(
    factory: UowFactory, alice: TenantContext, skyr: int, grams: float = 400.0
) -> None:
    uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    meal = uc.AddMeal(factory, alice).execute(DAY, "Breakfast")
    uc.AddLineItem(factory, alice).execute(
        meal.id, uc.LineItemInput(consumable_id=skyr, amount=grams, unit_code="g")
    )


def test_t_api_013_day_detail_computes_macros_and_zones(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-API-013 / T-SVC: GetDay returns view-computed macros, band zones and findings."""
    settings_uc.UpsertTargetBand(factory, alice).execute(BANDS["target_bands"][0])
    _day_with_skyr(factory, alice, skyr)
    view = uc.GetDay(factory, alice).execute(DAY)
    assert view.macros.kcal == 252  # 63 kcal/100 g × 400 g
    assert view.macros.protein == 44.0
    assert view.meals[0].line_items[0].kcal == pytest.approx(252.0)
    assert view.target_band is not None and view.target_band.name == "Rest day"
    assert view.zones["protein"] is BandZone.BELOW_MIN
    assert not any(f.kind == 0 for f in view.findings)


def test_count_unit_uses_the_portion(factory: UowFactory, alice: TenantContext, skyr: int) -> None:
    uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    meal = uc.AddMeal(factory, alice).execute(DAY, "Snack")
    item = uc.AddLineItem(factory, alice).execute(
        meal.id, uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="tub")
    )
    assert item.base_amount == 400.0
    assert item.base_unit == "g"
    with pytest.raises(ValidationFailed):
        uc.AddLineItem(factory, alice).execute(
            meal.id, uc.LineItemInput(consumable_id=skyr, amount=2, unit_code="slice")
        )


def test_t_svc_005_close_day_freezes_target_band(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-005: the band chosen at close time stays even when a newer band appears."""
    settings_uc.UpsertTargetBand(factory, alice).execute(BANDS["target_bands"][0])
    _day_with_skyr(factory, alice, skyr)
    closed = uc.CloseDay(factory, alice).execute(DAY)
    assert closed.status == "closed" and closed.target_band is not None
    frozen_id = closed.target_band.id
    newer = dict(BANDS["target_bands"][0], name="Rest day v2", valid_from="2026-03-01")
    settings_uc.UpsertTargetBand(factory, alice).execute(newer)
    assert uc.GetDay(factory, alice).execute(DAY).target_band.id == frozen_id  # type: ignore[union-attr]
    # a fresh day picks the newer band
    uc.CreateDay(factory, alice).execute(date(2026, 3, 11), reliable=True, training_type="rest")
    assert uc.GetDay(factory, alice).execute(date(2026, 3, 11)).target_band.name == "Rest day v2"  # type: ignore[union-attr]


def test_close_requires_reliable_flag(factory: UowFactory, alice: TenantContext) -> None:
    uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    uc.UpdateDayFlags(factory, alice).execute(DAY, {"reliable": None})
    with pytest.raises(ValidationFailed):
        uc.CloseDay(factory, alice).execute(DAY)


def test_t_svc_008_reassign_line_item_keeps_quantity(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-008: re-assigning to another consumable keeps the frozen base amount."""
    from victus.application.use_cases import products as products_uc

    quark = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Quark 20%", kcal=110, protein=12)
    )
    _day_with_skyr(factory, alice, skyr, grams=250)
    item = uc.GetDay(factory, alice).execute(DAY).meals[0].line_items[0]
    updated = uc.UpdateLineItem(factory, alice).execute(item.id, {"consumable_id": quark.id})
    assert updated.consumable_id == quark.id
    assert updated.base_amount == 250.0
    assert updated.kcal == pytest.approx(275.0)  # 110 × 2.5 — nutrients now from the new product


def test_t_svc_013_014_approve_day(factory: UowFactory, alice: TenantContext, skyr: int) -> None:
    """T-SVC-013/014: corrections applied, drafts cleared, `estimated` preserved,
    close flag honoured."""
    settings_uc.UpsertTargetBand(factory, alice).execute(BANDS["target_bands"][0])
    uc.CreateDay(factory, alice).execute(DAY, reliable=True, training_type="rest")
    meal = uc.AddMeal(factory, alice).execute(DAY, "Dinner")
    a = uc.AddLineItem(factory, alice).execute(
        meal.id,
        uc.LineItemInput(consumable_id=skyr, amount=400, unit_code="g", estimated=True),
        origin="agent",
        is_draft=True,
    )
    b = uc.AddLineItem(factory, alice).execute(
        meal.id,
        uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g"),
        origin="agent",
        is_draft=True,
    )
    drafts = drafts_uc.ListDrafts(factory, alice).execute()
    assert drafts and drafts[0].draft_items == 2 and drafts[0].estimated_items == 1
    summary = drafts_uc.DraftSummary(factory, alice).execute(DAY)
    assert "Skyr natural" in summary.markdown and "⚠️" in summary.markdown

    kept_open = drafts_uc.ApproveDay(factory, alice).execute(
        DAY,
        [
            drafts_uc.DraftCorrection(line_item_id=a.id, amount=300),
            drafts_uc.DraftCorrection(line_item_id=b.id, delete=True),
        ],
        close=False,
    )
    assert kept_open.status == "open" and kept_open.target_band is not None
    items = kept_open.meals[0].line_items
    assert len(items) == 1
    assert (
        items[0].base_amount == 300.0 and items[0].is_draft is False and items[0].estimated is True
    )
    assert drafts_uc.ListDrafts(factory, alice).execute() == []

    closed = drafts_uc.ApproveDay(factory, alice).execute(DAY, [], close=True)
    assert closed.status == "closed"


def test_discard_draft_removes_only_draft_items(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    _day_with_skyr(factory, alice, skyr)
    meal_id = uc.GetDay(factory, alice).execute(DAY).meals[0].id
    uc.AddLineItem(factory, alice).execute(
        meal_id,
        uc.LineItemInput(consumable_id=skyr, amount=50, unit_code="g"),
        origin="agent",
        is_draft=True,
    )
    assert drafts_uc.DiscardDraft(factory, alice).execute(DAY) == 1
    assert len(uc.GetDay(factory, alice).execute(DAY).meals[0].line_items) == 1


def test_t_svc_022_message_on_drafted_day_queues_follow_up(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-022: a message on a drafted day queues a follow_up run for that day only."""
    _day_with_skyr(factory, alice, skyr)
    meal_id = uc.GetDay(factory, alice).execute(DAY).meals[0].id
    uc.AddLineItem(factory, alice).execute(
        meal_id,
        uc.LineItemInput(consumable_id=skyr, amount=50, unit_code="g"),
        origin="agent",
        is_draft=True,
    )
    msg = uc.AddDayMessage(factory, alice).execute(DAY, "the skyr was 300 g")
    assert msg.role == "user" and msg.processing_state == "new"
    with factory(alice) as u:
        runs = u.agent.queued_runs()
        assert len(runs) == 1
        assert runs[0].mode == "follow_up" and runs[0].days == [DAY.isoformat()]
    thread = uc.GetDayThread(factory, alice).execute(DAY)
    assert [m.content for m in thread] == ["the skyr was 300 g"]
    # a message on a day without drafts queues nothing
    uc.AddDayMessage(factory, alice).execute(date(2026, 3, 12), "forgot an apple")
    with factory(alice) as u:
        assert len(u.agent.queued_runs()) == 1


def test_t_svc_023_message_while_locked_queues_follow_up(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-023: a live agent lock on the day counts like a draft."""
    with factory(alice) as u:
        assert u.agent.try_acquire_lock(DAY, "worker", "run-1", 5, datetime.now(UTC))
        u.commit()
    uc.AddDayMessage(factory, alice).execute(DAY, "and a coffee")
    with factory(alice) as u:
        assert [r.mode for r in u.agent.queued_runs()] == ["follow_up"]


def test_t_svc_007_manual_weight_only(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-007: only manual entries can be added or deleted through the app."""
    ts = datetime(2026, 3, 10, 7, 0, tzinfo=UTC)
    entry = weights_uc.AddManualWeight(factory, alice).execute(ts, 84.2)
    assert entry.source == "manual"
    with pytest.raises(Forbidden):
        weights_uc.AddManualWeight(factory, alice).execute(ts, 84.0, source="scale_sync")
    with pytest.raises(Conflict):
        weights_uc.AddManualWeight(factory, alice).execute(ts, 84.0)
    with factory(alice) as u:
        from victus.infrastructure.db import orm

        synced = u.weights.add(
            orm.WeightEntry(
                tenant_id=alice.tenant_id,
                measured_at=datetime(2026, 3, 11, 7, tzinfo=UTC),
                kg=84.0,
                source="scale_sync",
            )
        )
        u.commit()
        synced_id = synced.id
    with pytest.raises(Forbidden):
        weights_uc.DeleteManualWeight(factory, alice).execute(synced_id)
    weights_uc.DeleteManualWeight(factory, alice).execute(entry.id)
    assert [e.id for e in weights_uc.ListWeights(factory, alice).execute()] == [synced_id]


def test_t_svc_004_cook_batch_freezes_totals(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-004: batch totals are frozen at cooking time."""
    from victus.application.use_cases import products as products_uc

    r = recipes_uc.CreateRecipe(factory, alice).execute("Skyr bowl", 2)
    recipes_uc.SetIngredients(factory, alice).execute(
        r.id, [recipes_uc.IngredientInput(product_id=skyr, amount=500, unit_code="g")]
    )
    batch = recipes_uc.CookBatch(factory, alice).execute(r.id, cooked_at=DAY, total_weight_g=500)
    assert batch.kcal == pytest.approx(315.0)
    products_uc.UpdateProduct(factory, alice).execute(skyr, {"kcal": 100})
    assert recipes_uc.GetBatch(factory, alice).execute(batch.id).kcal == pytest.approx(315.0)


def test_t_svc_017_018_settings_versioning_and_band_sync(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-017/018: PUT settings versions the document and syncs bands;
    invalid documents are rejected."""
    doc = {
        "goal": {"weight_kg": 85.0, "date": "2027-03-31"},
        "kcal_per_kg": 7716.17,
        "calorie_corridor": {"min": 1800, "max": 2200, "asymmetric": True},
        **BANDS,
    }
    v1 = settings_uc.PutSettings(factory, alice).execute(doc, date(2026, 1, 1))
    assert v1.version == 1
    bands = settings_uc.ListTargetBands(factory, alice).execute()
    assert len(bands) == 1 and bands[0].salt.opt_max == 8
    v2 = settings_uc.PutSettings(factory, alice).execute(doc, date(2026, 6, 1))
    assert v2.version == 2
    assert [v.version for v in settings_uc.SettingsVersions(factory, alice).execute()] == [1, 2]
    with pytest.raises(ValidationFailed) as exc:
        settings_uc.PutSettings(factory, alice).execute({"kcal_per_kg": "seven"}, date(2026, 7, 1))
    assert exc.value.errors


def test_tenant_isolation_through_use_cases(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, skyr: int
) -> None:
    """T-SVC-016 (use-case level): Bob cannot see or use Alice's product or day."""
    _day_with_skyr(factory, alice, skyr)
    from victus.application.use_cases import products as products_uc

    with pytest.raises(NotFound):
        products_uc.GetProduct(factory, bob).execute(skyr)
    with pytest.raises(NotFound):
        uc.GetDay(factory, bob).execute(DAY)
    assert products_uc.SearchProducts(factory, bob).execute("skyr") == []
    uc.CreateDay(factory, bob).execute(DAY, reliable=True)
    meal = uc.AddMeal(factory, bob).execute(DAY, "Lunch")
    with pytest.raises(NotFound):
        uc.AddLineItem(factory, bob).execute(
            meal.id, uc.LineItemInput(consumable_id=skyr, amount=1, unit_code="g")
        )


def test_t_svc_067_weigh_ins_land_on_the_local_day(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-067: a weigh-in after local midnight belongs to the new day (R69).

    Half past midnight in Berlin is 23:30 UTC the day before, so grouping by the UTC
    date would put the reading on the wrong day and shift every average built on it.
    """
    from victus.application.schemas_loader import load_schema

    data = dict(load_schema("tenant-settings")["examples"][0])
    data["regional"] = {"timezone": "Europe/Berlin", "locale": "de-DE"}
    settings_uc.PutSettings(factory, alice).execute(data)

    weights_uc.AddManualWeight(factory, alice).execute(
        datetime(2026, 1, 5, 23, 30, tzinfo=UTC), 84.0
    )
    means = weights_uc.DailyMeans(factory, alice).execute(date(2026, 1, 6), date(2026, 1, 6))
    assert means == {date(2026, 1, 6): 84.0}

    # with the tenant on UTC the same reading counts on the fifth
    data["regional"] = {"timezone": "UTC", "locale": "en-GB"}
    settings_uc.PutSettings(factory, alice).execute(data)
    assert weights_uc.DailyMeans(factory, alice).execute(date(2026, 1, 5), date(2026, 1, 5)) == {
        date(2026, 1, 5): 84.0
    }
