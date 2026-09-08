"""T-SVC-044…049: meal rename/delete and product-linked captures."""

from __future__ import annotations

import pytest

from tests.integration.service.conftest import DAY
from victus.application.errors import Conflict, NotFound
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as uc
from victus.application.use_cases import day_logs as days_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def _day_with_meal(factory: UowFactory, alice: TenantContext) -> int:
    days_uc.CreateDay(factory, alice).execute(DAY, reliable=True)
    return days_uc.AddMeal(factory, alice).execute(DAY, "Lunch").id


def test_meal_rename_and_time(factory: UowFactory, alice: TenantContext) -> None:
    meal_id = _day_with_meal(factory, alice)
    import datetime as dt

    view = days_uc.UpdateMeal(factory, alice).execute(
        meal_id, {"name": "Dinner", "time": dt.time(19, 30)}
    )
    assert view.name == "Dinner" and view.time == dt.time(19, 30)


def test_meal_delete_only_when_empty(factory: UowFactory, alice: TenantContext, skyr: int) -> None:
    meal_id = _day_with_meal(factory, alice)
    days_uc.AddLineItem(factory, alice).execute(
        meal_id, days_uc.LineItemInput(consumable_id=skyr, amount=100, unit_code="g")
    )
    with pytest.raises(Conflict):
        days_uc.DeleteMeal(factory, alice).execute(meal_id)
    day = days_uc.GetDay(factory, alice).execute(DAY)
    item_id = day.meals[0].line_items[0].id
    days_uc.DeleteLineItem(factory, alice).execute(item_id)
    days_uc.DeleteMeal(factory, alice).execute(meal_id)
    assert days_uc.GetDay(factory, alice).execute(DAY).meals == []


def test_meal_of_other_tenant_is_invisible(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    meal_id = _day_with_meal(factory, alice)
    with pytest.raises(NotFound):
        days_uc.UpdateMeal(factory, bob).execute(meal_id, {"name": "x"})
    with pytest.raises(NotFound):
        days_uc.DeleteMeal(factory, bob).execute(meal_id)


def test_product_capture_has_no_day_and_queues_nothing(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    blobs = InMemoryBlobStorage()
    view = uc.UploadCapture(factory, alice, blobs).execute(
        uc.UploadInput(
            data=PNG, filename="label.png", mime="image/png", product_id=skyr, target_date=DAY
        )
    )
    assert view.product_id == skyr and view.target_date is None and view.kind == "image"
    assert agent_uc.ListAgentRuns(factory, alice).execute() == []
    only_product = uc.ListCaptures(factory, alice).execute(product_id=skyr)
    assert [c.id for c in only_product] == [view.id]
    # a day context never shows product captures
    ctx_view = agent_uc.GetDayContext(factory, alice).execute(DAY)
    assert ctx_view.captures == []


def test_product_capture_requires_own_product(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, skyr: int
) -> None:
    with pytest.raises(NotFound):
        uc.UploadCapture(factory, bob, InMemoryBlobStorage()).execute(
            uc.UploadInput(text="label says 70 kcal", product_id=skyr)
        )
    with pytest.raises(NotFound):
        uc.UploadCapture(factory, alice, InMemoryBlobStorage()).execute(
            uc.UploadInput(text="label says 70 kcal", product_id=999_999)
        )


def test_capture_can_be_relinked_to_product(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    cap = uc.UploadCapture(factory, alice, InMemoryBlobStorage()).execute(
        uc.UploadInput(text="skyr label: 63 kcal per 100 g")
    )
    view = uc.UpdateCapture(factory, alice).execute(cap.id, {"product_id": skyr})
    assert view.product_id == skyr
    view = uc.UpdateCapture(factory, alice).execute(cap.id, {"product_id": None})
    assert view.product_id is None
