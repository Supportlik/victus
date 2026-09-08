"""Product change proposals: the agent suggests, a person approves (SPEC R52, ADR 0003).

A label photo or a spoken correction attached to a product becomes a
*proposal* with the values the agent read. Approving writes them to the
product (values propagate to every logged quantity) and marks the product
verified; rejecting discards the capture. Nothing changes without a person.
"""

from __future__ import annotations

from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import SCOPE_AGENT_WRITE, SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase, now
from victus.application.use_cases.products import PRODUCT_FIELDS, UpdateProduct
from victus.domain.values import CaptureStatus
from victus.infrastructure.db import orm

# ``verified`` is proposable on purpose: a spoken "these values are correct" is a
# confirmation the person then approves, like any other proposal.
PROPOSABLE_FIELDS: frozenset[str] = frozenset(
    {*PRODUCT_FIELDS, "name", "brand", "ean", "note", "verified"}
) - {"category_id", "checked_at"}
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"


def _current_values(p: orm.Product, keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        if k == "name":
            out[k] = p.consumable.name
        else:
            out[k] = getattr(p, k, None)
    return out


def proposal_view(pr: orm.ProductProposal, product: orm.Product | None) -> dto.ProductProposalView:
    changes = dict(pr.changes or {})
    return dto.ProductProposalView(
        id=pr.id,
        product_id=pr.product_id,
        product_name=product.consumable.name if product is not None else None,
        capture_id=pr.capture_id,
        run_id=pr.run_id,
        changes=changes,
        current=_current_values(product, list(changes)) if product is not None else {},
        rationale=pr.rationale,
        source=pr.source,
        status=pr.status,
        created_at=pr.created_at,
        decided_at=pr.decided_at,
    )


class ProposeProductChange(UseCase):
    """Record what the agent read; requires ``agent:write`` (or ``write`` for a person)."""

    def execute(
        self,
        product_id: int,
        changes: dict[str, Any],
        *,
        rationale: str | None = None,
        source: str | None = None,
        capture_id: str | None = None,
        run_id: str | None = None,
    ) -> dto.ProductProposalView:
        if not (self.ctx.has_scope(SCOPE_AGENT_WRITE) or self.ctx.has_scope(SCOPE_WRITE)):
            self.ctx.require(SCOPE_AGENT_WRITE)
        clean = {k: v for k, v in changes.items() if v is not None}
        unknown = sorted(set(clean) - PROPOSABLE_FIELDS)
        if unknown:
            raise ValidationFailed(f"fields cannot be proposed: {', '.join(unknown)}")
        if not clean:
            raise ValidationFailed("a proposal needs at least one changed field")
        with self._uow() as uow:
            p = uow.products.get(product_id)
            if p is None:
                raise NotFound(f"product {product_id} not found")
            cap = uow.captures.get(capture_id) if capture_id else None
            if capture_id and cap is None:
                raise NotFound(f"capture {capture_id} not found")
            pr = uow.proposals.add(
                orm.ProductProposal(
                    tenant_id=self.ctx.tenant_id,
                    product_id=p.id,
                    capture_id=cap.id if cap else None,
                    run_id=run_id,
                    changes=clean,
                    rationale=rationale,
                    source=source,
                    status=PENDING,
                )
            )
            if cap is not None and cap.status in (
                CaptureStatus.NEW.value,
                CaptureStatus.IN_PROGRESS.value,
            ):
                cap.status = CaptureStatus.ASSIGNED.value
                cap.agent_run_id = run_id or cap.agent_run_id
            uow.audit.record(
                "product.propose", "product", str(p.id), {"proposal": pr.id, "changes": clean}
            )
            uow.flush()
            view = proposal_view(pr, p)
            uow.commit()
            return view


class ListProposals(UseCase):
    def execute(
        self, *, status: str | None = PENDING, product_id: int | None = None, limit: int = 200
    ) -> list[dto.ProductProposalView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.proposals.list(status=status, product_id=product_id, limit=limit)
            return [proposal_view(pr, uow.products.get(pr.product_id)) for pr in rows]


class GetProposal(UseCase):
    def execute(self, proposal_id: str) -> dto.ProductProposalView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            pr = uow.proposals.get(proposal_id)
            if pr is None:
                raise NotFound(f"proposal {proposal_id} not found")
            return proposal_view(pr, uow.products.get(pr.product_id))


class DecideProposal(UseCase):
    """Approve (apply + verify) or reject a pending proposal; a human decision (``write``)."""

    def execute(
        self,
        proposal_id: str,
        *,
        approve: bool,
        changes: dict[str, Any] | None = None,
        fields: list[str] | None = None,
    ) -> dto.ProductProposalView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            pr = uow.proposals.get(proposal_id)
            if pr is None:
                raise NotFound(f"proposal {proposal_id} not found")
            if pr.status != PENDING:
                raise Conflict(f"proposal {proposal_id} is already {pr.status}")
            applied: dict[str, Any] = dict(pr.changes or {})
            if fields is not None:
                unknown = sorted(set(fields) - set(applied))
                if unknown:
                    raise ValidationFailed(f"not part of this proposal: {', '.join(unknown)}")
                if not fields:
                    raise ValidationFailed("select at least one field, or reject the proposal")
                applied = {k: v for k, v in applied.items() if k in fields}
            if changes:
                unknown = sorted(set(changes) - PROPOSABLE_FIELDS)
                if unknown:
                    raise ValidationFailed(f"fields cannot be applied: {', '.join(unknown)}")
                applied.update({k: v for k, v in changes.items() if v is not None})
            pr.status = APPROVED if approve else REJECTED
            pr.decided_at = now()
            pr.decided_by = self.ctx.actor_id
            if approve and (changes or fields is not None):
                pr.changes = applied
            cap = uow.captures.get(pr.capture_id) if pr.capture_id else None
            if cap is not None:
                cap.status = (
                    CaptureStatus.PROCESSED.value if approve else CaptureStatus.DISCARDED.value
                )
                cap.processed_at = pr.decided_at
            uow.audit.record(
                "product.proposal.decide",
                "product",
                str(pr.product_id),
                {"proposal": pr.id, "approve": approve, "changes": applied if approve else None},
            )
            uow.flush()
            uow.commit()
        if approve:
            apply = dict(applied)
            if pr.source and "source" not in apply:
                apply["source"] = pr.source
            apply["verified"] = True  # a person looked at the label photo and approved it
            UpdateProduct(self.uow_factory, self.ctx).execute(pr.product_id, apply)
        with self._uow() as uow:
            fresh = uow.proposals.get(proposal_id)
            assert fresh is not None
            return proposal_view(fresh, uow.products.get(fresh.product_id))


def pending_count(uow: UnitOfWork) -> int:
    return len(uow.proposals.list(status=PENDING, limit=10_000))
