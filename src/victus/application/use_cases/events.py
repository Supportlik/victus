"""The change feed behind the server-sent events channel (SPEC R83).

Every write in the application records an audit entry, wherever it came from: the
API, the worker container, an MCP client. ``MAX(audit_log.id)`` per tenant is
therefore a cursor that is monotonic, cheap to read and — unlike an in-process
event bus — complete across processes. A listener compares the cursor it holds
with the current one; a higher number means something changed.

What travels back is the cursor, the four badge counts and *which* rows moved —
action, target type, target id. **Never the ``diff``**: the channel says that the
day changed, not what was eaten.
"""

from __future__ import annotations

from victus.application import dto
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_CAPTURE_READ, SCOPE_READ
from victus.application.use_cases._base import UseCase
from victus.application.use_cases.settings import regional_of
from victus.domain.services.calendar import today_in

#: Newest entries carried in one ``change`` event. Beyond this the payload says it
#: was truncated and the client reloads rather than patching what it has.
MAX_TARGETS = 50


def counts_for(uow: UnitOfWork) -> dto.ChangeCounts:
    """The four numbers the navigation badges show, counted in one place so the
    badges, the push channel and any future caller cannot drift apart.

    ``open_days`` deliberately excludes today: a day is expected to be open while
    it is being lived, and only an unfinished *past* day is something to act on.
    Which day is today follows the tenant's timezone (R69), not the server's.
    """
    today = today_in(regional_of(uow).timezone)
    return dto.ChangeCounts(
        new_captures=uow.captures.count(status="new"),
        draft_days=uow.day_logs.count_drafts(),
        open_days=uow.day_logs.count_open_before(today),
        pending_proposals=uow.proposals.count(status="pending"),
    )


class InboxState(UseCase):
    """Where the tenant stands right now: the cursor and the four counts, without
    the history behind them. This is what a listener is greeted with."""

    def execute(self) -> dto.ChangeView:
        self.ctx.require(SCOPE_READ)
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            return dto.ChangeView(cursor=uow.audit.max_id(), counts=counts_for(uow))


class ChangeCursor(UseCase):
    """The tenant's current cursor. This is the one query the poll loop repeats,
    so it stays a single ``MAX(id)`` and opens no transaction of its own."""

    def execute(self) -> int:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return uow.audit.max_id()


class ChangesSince(UseCase):
    """Cursor, counts and the targets that moved since ``cursor``.

    Called on connect (with the client's resume point, or the current cursor,
    which yields no targets) and whenever the cursor has advanced.
    """

    def execute(self, cursor: int, limit: int = MAX_TARGETS) -> dto.ChangeView:
        self.ctx.require(SCOPE_READ)
        self.ctx.require(SCOPE_CAPTURE_READ)
        with self._uow() as uow:
            latest = uow.audit.max_id()
            rows = uow.audit.since(cursor, limit + 1) if latest > cursor else []
            truncated = len(rows) > limit
            return dto.ChangeView(
                cursor=latest,
                counts=counts_for(uow),
                targets=[
                    dto.ChangeTarget(action=r.action, type=r.target_type, id=r.target_id)
                    for r in rows[-limit:]
                ],
                truncated=truncated,
            )
