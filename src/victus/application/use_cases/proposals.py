"""Product change proposals: the agent suggests, a person approves (SPEC R52, R81, ADR 0003).

A label photo or a spoken correction attached to a product becomes a
*proposal* with the values the agent read. Approving writes them to the
product (values propagate to every logged quantity) and marks the product
verified; rejecting discards the capture. Nothing changes without a person.

A food nobody has logged before takes the same road (``kind='new'``): the values
land on a **one-off consumable**, so the day can be drafted with correct macros
right away, and the catalogue entry appears only when a person approves — then the
one-off is *promoted* in place, keeping every line item that already points at it.
"""

from __future__ import annotations

from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.ports.unit_of_work import UnitOfWork
from victus.application.tenant_context import (
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_READ,
    SCOPE_WRITE,
)
from victus.application.use_cases._base import UseCase, now, require_decision
from victus.application.use_cases.products import (
    PRODUCT_FIELDS,
    AddPortion,
    CreateProduct,
    PortionInput,
    ProductInput,
    UpdateProduct,
    _resolve_category,
    _validate_product,
)
from victus.domain.values import CaptureStatus
from victus.infrastructure.db import orm

# ``verified`` is proposable on purpose: a spoken "these values are correct" is a
# confirmation the person then approves, like any other proposal.
PROPOSABLE_FIELDS: frozenset[str] = frozenset(
    {*PRODUCT_FIELDS, "name", "brand", "ean", "note", "verified", "portions"}
) - {"category_id", "checked_at"}
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
UPDATE, NEW = "update", "new"


def _current_values(p: orm.Product, keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        if k == "name":
            out[k] = p.consumable.name
        else:
            out[k] = getattr(p, k, None)
    return out


def _product_of(uow: UnitOfWork, pr: orm.ProductProposal) -> orm.Product | None:
    """A pending ``new`` proposal has no product yet."""
    return uow.products.get(pr.product_id) if pr.product_id is not None else None


def proposal_view(pr: orm.ProductProposal, product: orm.Product | None) -> dto.ProductProposalView:
    changes = dict(pr.changes or {})
    name = product.consumable.name if product is not None else changes.get("name")
    return dto.ProductProposalView(
        id=pr.id,
        product_id=pr.product_id,
        product_name=name,
        capture_id=pr.capture_id,
        run_id=pr.run_id,
        changes=changes,
        current=_current_values(product, list(changes)) if product is not None else {},
        rationale=pr.rationale,
        source=pr.source,
        status=pr.status,
        created_at=pr.created_at,
        decided_at=pr.decided_at,
        kind=pr.kind,
        consumable_id=pr.consumable_id,
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


#: Fields a ``new`` proposal carries; ``portions`` is a list, the rest are product columns.
NEW_PRODUCT_FIELDS: frozenset[str] = frozenset({*PROPOSABLE_FIELDS, "category", "portions"}) - {
    "verified"
}


class ProposeNewProduct(UseCase):
    """A food nobody has logged before: values now, catalogue entry after review (R81).

    The values land on a one-off consumable, so the day it was eaten can be drafted
    with correct macros immediately. Approving the proposal promotes that consumable
    into a product; rejecting leaves the meal untouched and the catalogue clean.
    """

    def execute(
        self,
        data: ProductInput,
        *,
        portions: list[dict[str, Any]] | None = None,
        rationale: str | None = None,
        capture_id: str | None = None,
        run_id: str | None = None,
    ) -> dto.ProductProposalView:
        if not (self.ctx.has_scope(SCOPE_AGENT_WRITE) or self.ctx.has_scope(SCOPE_WRITE)):
            self.ctx.require(SCOPE_AGENT_WRITE)
        _validate_product(data)
        changes: dict[str, Any] = {
            k: v
            for k, v in (
                ("name", data.name.strip()),
                ("brand", data.brand),
                ("icon", data.icon),
                ("category", data.category),
                ("reference_amount", data.reference_amount),
                ("reference_unit", data.reference_unit),
                ("density_g_per_ml", data.density_g_per_ml),
                ("kcal", data.kcal),
                ("protein", data.protein),
                ("carbs", data.carbs),
                ("fat", data.fat),
                ("fiber", data.fiber),
                ("salt", data.salt),
                ("source", data.source),
                ("note", data.note),
                ("ean", data.ean),
            )
            if v is not None
        }
        if portions:
            changes["portions"] = portions
        with self._uow() as uow:
            if uow.products.by_name(data.name) is not None:
                raise Conflict(
                    f"product '{data.name}' already exists; propose a change to it instead"
                )
            cap = uow.captures.get(capture_id) if capture_id else None
            if capture_id and cap is None:
                raise NotFound(f"capture {capture_id} not found")
            ad = uow.products.add_ad_hoc_item(
                data.name.strip()[:300],
                reference_amount=data.reference_amount,
                reference_unit=data.reference_unit,
                kcal=data.kcal,
                protein=data.protein,
                carbs=data.carbs,
                fat=data.fat,
                fiber=data.fiber,
                salt=data.salt,
                origin_text=(data.source or rationale or "")[:500] or None,
            )
            pr = uow.proposals.add(
                orm.ProductProposal(
                    tenant_id=self.ctx.tenant_id,
                    product_id=None,
                    kind=NEW,
                    consumable_id=ad.id,
                    capture_id=cap.id if cap else None,
                    run_id=run_id,
                    changes=changes,
                    rationale=rationale,
                    source=data.source,
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
                "product.propose_new",
                "consumable",
                str(ad.id),
                {"proposal": pr.id, "name": changes["name"]},
            )
            uow.flush()
            view = proposal_view(pr, None)
            uow.commit()
            return view


class ListProposals(UseCase):
    def execute(
        self, *, status: str | None = PENDING, product_id: int | None = None, limit: int = 200
    ) -> list[dto.ProductProposalView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.proposals.list(status=status, product_id=product_id, limit=limit)
            return [proposal_view(pr, _product_of(uow, pr)) for pr in rows]


class GetProposal(UseCase):
    def execute(self, proposal_id: str) -> dto.ProductProposalView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            pr = uow.proposals.get(proposal_id)
            if pr is None:
                raise NotFound(f"proposal {proposal_id} not found")
            return proposal_view(pr, _product_of(uow, pr))


class DecideProposal(UseCase):
    """Approve (apply + verify) or reject a pending proposal; a human decision.

    Needs ``approve``: whoever may decide a proposal may write the product, so
    ``write`` alone must not reach it — otherwise the agent could wave through its
    own reading of a label (R54, R81).
    """

    def execute(
        self,
        proposal_id: str,
        *,
        approve: bool,
        changes: dict[str, Any] | None = None,
        fields: list[str] | None = None,
    ) -> dto.ProductProposalView:
        require_decision(self.ctx)
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
            allowed = NEW_PRODUCT_FIELDS if pr.kind == NEW else PROPOSABLE_FIELDS
            if changes:
                unknown = sorted(set(changes) - allowed)
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
                "product" if pr.kind == UPDATE else "consumable",
                str(pr.product_id if pr.kind == UPDATE else pr.consumable_id),
                {
                    "proposal": pr.id,
                    "kind": pr.kind,
                    "approve": approve,
                    "changes": applied if approve else None,
                },
            )
            uow.flush()
            kind, product_id, consumable_id = pr.kind, pr.product_id, pr.consumable_id
            source = pr.source
            uow.commit()
        if approve:
            apply = dict(applied)
            if source and "source" not in apply:
                apply["source"] = source
            apply["verified"] = True  # a person looked at the label photo and approved it
            if kind == NEW:
                assert consumable_id is not None
                product_id = self._promote(consumable_id, apply)
            else:
                assert product_id is not None
                portions = apply.pop("portions", None) or []
                UpdateProduct(self.uow_factory, self.ctx).execute(product_id, apply)
                for portion in portions:
                    AddPortion(self.uow_factory, self.ctx).execute(
                        product_id,
                        PortionInput(
                            unit_code=str(portion["unit_code"]),
                            label=str(portion.get("label") or portion["unit_code"]),
                            amount=float(portion["amount"]),
                            amount_unit=str(portion.get("amount_unit") or "g"),
                            description=portion.get("description"),
                            is_default=bool(portion.get("is_default", False)),
                            weight_source=portion.get("weight_source"),
                        ),
                    )
        with self._uow() as uow:
            fresh = uow.proposals.get(proposal_id)
            assert fresh is not None
            if approve and kind == NEW and fresh.product_id is None:
                fresh.product_id = product_id  # the entry it created, for the review history
                uow.flush()
                uow.commit()
            return proposal_view(fresh, _product_of(uow, fresh))

    def _promote(self, consumable_id: int, values: dict[str, Any]) -> int:
        """Make the pending one-off a catalogue product, keeping every logged line item."""
        portions = values.pop("portions", None) or []
        name = str(values.pop("name", "")).strip()
        with self._uow() as uow:
            consumable = uow.products.get_consumable(consumable_id)
            if consumable is None:
                raise NotFound(f"consumable {consumable_id} not found")
            if consumable.kind == "product":  # a second decision on the same proposal
                raise Conflict(f"consumable {consumable_id} is already a product")
            if not name:
                name = consumable.name
            other = uow.products.by_name(name)
            if other is not None:
                raise Conflict(f"product '{name}' already exists")
            category_id = _resolve_category(
                uow, ProductInput(name=name, category=values.pop("category", None))
            )
            fields = {k: values.get(k) for k in PRODUCT_FIELDS if k in values}
            fields["category_id"] = category_id
            product = uow.products.promote_ad_hoc(consumable_id, name, **fields)
            uow.audit.record(
                "product.promote", "product", str(product.id), {"name": name, "from": "ad_hoc"}
            )
            uow.flush()
            uow.commit()
            product_id = product.id
        for portion in portions:
            AddPortion(self.uow_factory, self.ctx).execute(
                product_id,
                PortionInput(
                    unit_code=str(portion["unit_code"]),
                    label=str(portion.get("label") or portion["unit_code"]),
                    amount=float(portion["amount"]),
                    amount_unit=str(portion.get("amount_unit") or "g"),
                    description=portion.get("description"),
                    is_default=bool(portion.get("is_default", False)),
                    weight_source=portion.get("weight_source"),
                ),
            )
        return product_id


def pending_count(uow: UnitOfWork) -> int:
    return len(uow.proposals.list(status=PENDING, limit=10_000))


# ── the one door for catalogue writes (R81) ─────────────────────────────────
#
# Adapters call these instead of the use cases directly: with ``approve`` the value
# is written, without it the same call becomes a proposal a person decides. That way
# the rule lives in the application layer and no adapter has to remember it.


def create_or_propose_product(
    uow_factory: Any,
    ctx: Any,
    data: ProductInput,
    *,
    portions: list[dict[str, Any]] | None = None,
    rationale: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.ProductView | dto.ProductProposalView:
    if ctx.has_scope(SCOPE_APPROVE):
        product = CreateProduct(uow_factory, ctx).execute(data)
        for portion in portions or []:
            AddPortion(uow_factory, ctx).execute(
                product.id,
                PortionInput(
                    unit_code=str(portion["unit_code"]),
                    label=str(portion.get("label") or portion["unit_code"]),
                    amount=float(portion["amount"]),
                    amount_unit=str(portion.get("amount_unit") or "g"),
                    is_default=bool(portion.get("is_default", False)),
                ),
            )
        return product
    return ProposeNewProduct(uow_factory, ctx).execute(
        data, portions=portions, rationale=rationale, capture_id=capture_id, run_id=run_id
    )


def update_or_propose_product(
    uow_factory: Any,
    ctx: Any,
    product_id: int,
    changes: dict[str, Any],
    *,
    rationale: str | None = None,
    source: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.ProductView | dto.ProductProposalView:
    if ctx.has_scope(SCOPE_APPROVE):
        return UpdateProduct(uow_factory, ctx).execute(product_id, changes)
    return ProposeProductChange(uow_factory, ctx).execute(
        product_id,
        changes,
        rationale=rationale,
        source=source or changes.get("source"),
        capture_id=capture_id,
        run_id=run_id,
    )


def add_or_propose_portion(
    uow_factory: Any,
    ctx: Any,
    product_id: int,
    portion: dict[str, Any],
    *,
    rationale: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.PortionView | dto.ProductProposalView:
    if ctx.has_scope(SCOPE_APPROVE):
        return AddPortion(
            uow_factory,
            ctx,
        ).execute(
            product_id,
            PortionInput(
                unit_code=str(portion["unit_code"]),
                label=str(portion.get("label") or portion["unit_code"]),
                amount=float(portion["amount"]),
                amount_unit=str(portion.get("amount_unit") or "g"),
                description=portion.get("description"),
                is_default=bool(portion.get("is_default", False)),
                weight_source=portion.get("weight_source"),
            ),
        )
    return ProposeProductChange(uow_factory, ctx).execute(
        product_id,
        {"portions": [portion]},
        rationale=rationale,
        capture_id=capture_id,
        run_id=run_id,
    )
