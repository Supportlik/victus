"""The change feed the SSE endpoint reads (SPEC R83): counts, cursor, truncation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from victus.application.tenant_context import TenantContext
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import events as uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as proposals_uc
from victus.application.use_cases._base import UowFactory
from victus.domain.services.calendar import DEFAULT_TIMEZONE, today_in
from victus.infrastructure.storage.memory import InMemoryBlobStorage

pytestmark = pytest.mark.service

TODAY = today_in(DEFAULT_TIMEZONE)
YESTERDAY = TODAY - timedelta(days=1)


def test_the_four_counts_are_the_badges(
    factory: UowFactory, alice: TenantContext, bob: TenantContext, skyr: int
) -> None:
    """T-SVC-110: what the navigation shows, counted once, per tenant.

    Today's day is open because it is being lived; only an unfinished *past* day is
    something to act on, which is the distinction the badge made client-side before.
    """
    blobs = InMemoryBlobStorage()
    empty = uc.InboxState(factory, alice).execute().counts
    assert (empty.new_captures, empty.draft_days, empty.open_days, empty.pending_proposals) == (
        0,
        0,
        0,
        0,
    )

    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="two slices of bread")
    )
    day_uc.CreateDay(factory, alice).execute(TODAY, reliable=True)
    day_uc.CreateDay(factory, alice).execute(YESTERDAY, reliable=True)
    proposals_uc.ProposeProductChange(factory, alice).execute(skyr, {"kcal": 64.0})
    # another tenant's inbox is none of Alice's business
    day_uc.CreateDay(factory, bob).execute(YESTERDAY, reliable=True)

    counts = uc.InboxState(factory, alice).execute().counts
    assert counts.new_captures == 1
    assert counts.open_days == 1  # yesterday only
    assert counts.draft_days == 0
    assert counts.pending_proposals == 1
    assert uc.InboxState(factory, bob).execute().counts.new_captures == 0

    day_uc.CloseDay(factory, alice).execute(YESTERDAY)
    assert uc.InboxState(factory, alice).execute().counts.open_days == 0


def test_a_long_backlog_is_capped_and_says_so(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-111: past the cap the newest targets are kept and `truncated` is set.

    The cursor and the counts stay exact, so a client that fell behind can reload
    instead of trying to patch what it has from an incomplete list.
    """
    start = uc.ChangeCursor(factory, alice).execute()
    for kcal in range(60, 65):
        products_uc.UpdateProduct(factory, alice).execute(skyr, {"kcal": float(kcal)})

    everything = uc.ChangesSince(factory, alice).execute(start)
    assert len(everything.targets) == 5 and everything.truncated is False
    assert {t.type for t in everything.targets} == {"product"}

    capped = uc.ChangesSince(factory, alice).execute(start, limit=2)
    assert capped.truncated is True
    assert capped.cursor == everything.cursor
    assert [t.id for t in capped.targets] == [t.id for t in everything.targets[-2:]]

    # nothing new since the last cursor: no targets, and nothing to say about them
    quiet = uc.ChangesSince(factory, alice).execute(everything.cursor)
    assert quiet.targets == [] and quiet.truncated is False
