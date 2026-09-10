"""Product change proposals: the agent suggests, a person approves (SPEC R52, R81, ADR 0003).

A label photo or a spoken correction attached to a product becomes a
*proposal* with the values the agent read. Approving writes them to the
product (values propagate to every logged quantity) and marks the product
verified; rejecting discards the capture. Nothing changes without a person.

A food nobody has logged before takes the same road (``kind='new'``): the values
land on a **one-off consumable**, so the day can be drafted with correct macros
right away, and the catalogue entry appears only when a person approves — then the
one-off is *promoted* in place, keeping every line item that already points at it.

A product's portions travel in ``changes['portions']``, one object per portion,
each naming what it does: ``add``, ``update`` or ``delete``. Anything a person may
decide about a portion is therefore something an actor can draft, which is what ADR
0013 asks for — before, only adding could be proposed, so correcting a wrong unit or
removing a duplicate needed the ``approve`` scope the review gate exists to withhold.

A recipe that changed takes the third road (``kind='version'``): ``changes`` carries a
``valid_from`` and the new values, and approving opens a version from that day, leaving
the days before it counted as they were eaten. Proposing a plain correction instead
would rewrite them (R70).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, replace
from datetime import date
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
from victus.application.use_cases._mappers import portion_view
from victus.application.use_cases.products import (
    PRODUCT_FIELDS,
    AddPortion,
    CreateProduct,
    DeletePortion,
    NewProductVersion,
    PortionInput,
    ProductInput,
    UpdatePortion,
    UpdateProduct,
    _resolve_category,
    _validate_product,
    check_new_version,
    portion_unit_problem,
)
from victus.domain.services.units import UNITS
from victus.domain.values import CaptureStatus
from victus.infrastructure.db import orm

# ``verified`` is proposable on purpose: a spoken "these values are correct" is a
# confirmation the person then approves, like any other proposal.
PROPOSABLE_FIELDS: frozenset[str] = frozenset(
    {*PRODUCT_FIELDS, "name", "brand", "ean", "note", "verified", "portions"}
) - {"category_id", "checked_at"}
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
UPDATE, NEW, VERSION = "update", "new", "version"

#: What a ``version`` proposal may carry. ``valid_from`` is the day the new values start
#: on, so a person can move the date while approving. ``portions`` cannot travel with one:
#: the rows it could name belong to the version being replaced, and approving copies them
#: onto a version whose portions do not exist while the proposal is pending.
VERSION_FIELDS: frozenset[str] = frozenset({*PROPOSABLE_FIELDS, "category", "valid_from"}) - {
    "portions"
}

#: What one entry of ``changes['portions']`` does. An entry **without** ``op`` adds:
#: proposals filed before the other two operations existed are stored that way and
#: must still approve as they did.
PORTION_ADD, PORTION_UPDATE, PORTION_DELETE = "add", "update", "delete"
PORTION_OPS = (PORTION_ADD, PORTION_UPDATE, PORTION_DELETE)
#: The fields a portion entry may carry, i.e. what ``AddPortion``/``UpdatePortion`` take.
PORTION_FIELDS = (
    "unit_code",
    "label",
    "description",
    "amount",
    "amount_unit",
    "is_default",
    "weight_source",
)


def _current_values(p: orm.Product, keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        if k == "portions":
            continue  # not one value to compare: the rows are in ``portion_plan``
        if k == "name":
            out[k] = p.consumable.name
        else:
            out[k] = getattr(p, k, None)
    return out


def _product_of(uow: UnitOfWork, pr: orm.ProductProposal) -> orm.Product | None:
    """A pending ``new`` proposal has no product yet."""
    return uow.products.get(pr.product_id) if pr.product_id is not None else None


def _op_of(entry: dict[str, Any]) -> str:
    return str(entry.get("op") or PORTION_ADD)


def _version_day(value: Any) -> date:
    """``valid_from`` travels as an ISO day, because ``changes`` is stored as JSON."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationFailed("valid_from must be a day, as YYYY-MM-DD") from None


def _assign_capture(cap: orm.Capture | None, run_id: str | None) -> None:
    """A capture a proposal was read from is no longer waiting for an actor to pick up."""
    if cap is None or cap.status not in (
        CaptureStatus.NEW.value,
        CaptureStatus.IN_PROGRESS.value,
    ):
        return
    cap.status = CaptureStatus.ASSIGNED.value
    cap.agent_run_id = run_id or cap.agent_run_id


def _validated_portions(entries: Any, *, adds_only: bool = False) -> list[dict[str, Any]]:
    """Check a ``portions`` list before it is stored, and write ``op`` into every entry.

    Storing the operation even where it is the default keeps the proposal readable on its
    own; reading tolerates its absence, because that is how older rows look.
    """
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise ValidationFailed("portions must be a list of objects")
    out: list[dict[str, Any]] = []
    for entry in entries:
        op = _op_of(entry)
        if op not in PORTION_OPS:
            raise ValidationFailed(
                f"unknown portion operation '{op}'; use one of {', '.join(PORTION_OPS)}"
            )
        if adds_only and op != PORTION_ADD:
            raise ValidationFailed(f"a product that does not exist yet has no portion to {op}")
        if op == PORTION_ADD:
            if not entry.get("unit_code"):
                raise ValidationFailed("a portion to add needs a unit_code")
            try:
                amount = float(entry["amount"])
            except (KeyError, TypeError, ValueError):
                raise ValidationFailed("a portion to add needs a positive amount") from None
            if amount <= 0:
                raise ValidationFailed("a portion to add needs a positive amount")
        else:
            if not isinstance(entry.get("portion_id"), int):
                raise ValidationFailed(f"a portion to {op} needs its portion_id")
            if op == PORTION_UPDATE and not any(k in entry for k in PORTION_FIELDS):
                raise ValidationFailed(
                    f"an update needs at least one of: {', '.join(PORTION_FIELDS)}"
                )
        out.append({**entry, "op": op})
    return out


#: What a portion's weight may be stated in. ``unit_code`` — what it is a portion *of* —
#: comes from the ``unit`` table instead, which is the confusion issue #25 was made of.
AMOUNT_UNITS = ("g", "ml")


@dataclass(frozen=True, slots=True)
class PortionReference:
    """The values a portion's ``amount_unit`` has to agree with (R75).

    They are not simply the product's: a ``new`` proposal has no product row yet, and an
    ``update`` is applied to the product's own fields before its portions, so a proposal
    that moves the reference unit and adds a portion measured in the new one is one change.
    """

    reference_amount: float = 100.0
    reference_unit: str = "g"
    density_g_per_ml: float | None = None


REFERENCE_FIELDS = ("reference_amount", "reference_unit", "density_g_per_ml")


def _reference_of(product: orm.Product | None, changes: dict[str, Any]) -> PortionReference:
    """What the reference values will be once this proposal has been applied."""
    base = (
        PortionReference(
            reference_amount=product.reference_amount,
            reference_unit=product.reference_unit,
            density_g_per_ml=product.density_g_per_ml,
        )
        if product is not None
        else PortionReference()
    )
    proposed = {k: changes[k] for k in REFERENCE_FIELDS if changes.get(k) is not None}
    return replace(base, **proposed) if proposed else base


def _unit_problem(code: Any) -> str | None:
    """Why ``unit_code`` names no unit, or ``None`` — what ``AddPortion`` refuses first.

    The refusal this exists for arrived over MCP as ``piece_s`` … ``piece_xl``: the size of
    an egg written where the unit belongs. Naming the nearest real code turns the reason
    into the fix, since the size itself has a home in the label.
    """
    unit = str(code)
    if unit in UNITS:
        return None
    near = difflib.get_close_matches(unit, UNITS, n=1)
    hint = f"; did you mean '{near[0]}'?" if near else ""
    return f"there is no unit '{unit}'; a size belongs in the portion's label{hint}"


def _amount_problem(value: Any) -> str | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return f"'{value}' is not an amount; a portion needs a positive number"
    return None if amount > 0 else "a portion needs a positive amount"


def _measure_problem(amount_unit: str, reference: PortionReference) -> str | None:
    if amount_unit not in AMOUNT_UNITS:
        return f"a portion's amount is in g or ml, not '{amount_unit}'"
    return portion_unit_problem(
        amount_unit,
        reference_amount=reference.reference_amount,
        reference_unit=reference.reference_unit,
        density_g_per_ml=reference.density_g_per_ml,
    )


def _add_problem(values: dict[str, Any], reference: PortionReference) -> str | None:
    """Everything ``AddPortion`` refuses before the database sees the row, in its order."""
    if not values.get("unit_code"):
        return "a portion to add needs a unit_code"
    return (
        _unit_problem(values["unit_code"])
        or _amount_problem(values.get("amount"))
        or _measure_problem(str(values.get("amount_unit") or "g"), reference)
    )


def _update_problem(
    values: dict[str, Any], current: orm.Portion, reference: PortionReference
) -> str | None:
    """The same refusals, for the fields an update carries.

    ``UpdatePortion`` skips a field given as ``None`` and keeps what the row holds, so the
    unit R75 is read against is the one the row would end up with, not the one given here.
    """
    if not values:
        return f"an update needs at least one of: {', '.join(PORTION_FIELDS)}"
    code, amount = values.get("unit_code"), values.get("amount")
    return (
        (_unit_problem(code) if code is not None else None)
        or (_amount_problem(amount) if amount is not None else None)
        or _measure_problem(str(values.get("amount_unit") or current.amount_unit), reference)
    )


def _missing_portion(uow: UnitOfWork, portion_id: int) -> str:
    """A ``portion_id`` this product does not own: removed since, or somebody else's row."""
    other = uow.products.get_portion(portion_id)
    if other is not None:
        return f"portion {portion_id} belongs to product {other.product_id}, not to this one"
    return f"portion {portion_id} no longer exists"


def portion_plan(
    uow: UnitOfWork,
    product_id: int | None,
    entries: Any,
    *,
    reference: PortionReference | None = None,
) -> list[dto.PortionOperationView]:
    """Read each portion entry against the catalogue as it stands (R81).

    The reviewer sees the proposal, not the product, so every refusal approving would run
    into is resolved here and named in the view: a unit that is not a unit, an amount that
    is not one, a unit R75 will not allow, a portion that has since gone or was never this
    product's, a twin under the unique ``(product, unit, label)``, and the ``RESTRICT`` on
    a portion days already point at. Approving then fails before it changes anything —
    or, where the plan is clean, does not fail at all. A line that says nothing is wrong
    is the one a reviewer clicks, so a refusal this does not model is a refusal they meet
    afterwards, which is what the plan exists to prevent.

    The entries are read in the order they will be applied, and ``taken`` follows along:
    a proposal that removes the wrong-unit twin and adds the right portion is a swap, not
    a duplicate, and must not be refused for the row it removes first.
    """
    if not isinstance(entries, list):
        return []
    existing = {p.id: p for p in uow.products.portions_for(product_id)} if product_id else {}
    if reference is None:
        reference = _reference_of(uow.products.get(product_id) if product_id else None, {})
    taken = {p.id: (p.unit_code, p.label) for p in existing.values()}
    queued: set[tuple[str, str]] = set()  # pairs this proposal adds itself
    rows: list[dto.PortionOperationView] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        op = _op_of(entry)
        values = {k: entry[k] for k in PORTION_FIELDS if k in entry}
        raw_id = entry.get("portion_id")
        portion_id = raw_id if isinstance(raw_id, int) else None
        current = existing.get(portion_id) if portion_id is not None else None
        used_by, blocked = 0, None
        if op not in PORTION_OPS:
            blocked = f"there is no portion operation '{op}'; use one of {', '.join(PORTION_OPS)}"
        elif op != PORTION_ADD and product_id is None:
            blocked = f"a product that does not exist yet has no portion to {op}"
        elif op == PORTION_ADD:
            unit = str(values.get("unit_code") or "")
            wanted = (unit, str(values.get("label") or unit))
            twin = next((pid for pid, pair in taken.items() if pair == wanted), None)
            blocked = _add_problem(values, reference)
            if blocked is not None:
                pass  # what the values say is wrong comes before what the catalogue holds
            elif wanted in queued:
                blocked = f"this proposal already adds '{wanted[1]}' in {wanted[0]}"
            elif twin is not None:
                blocked = f"portion {twin} already carries '{wanted[1]}' in {wanted[0]}"
            else:
                queued.add(wanted)
        elif portion_id is None:
            blocked = f"a portion to {op} needs its portion_id"
        elif current is None:
            blocked = _missing_portion(uow, portion_id)
        elif op == PORTION_UPDATE:
            wanted = (
                str(values.get("unit_code") or current.unit_code),
                str(values.get("label") or current.label),
            )
            twin = next(
                (pid for pid, pair in taken.items() if pair == wanted and pid != current.id), None
            )
            used_by = uow.products.portion_usage(current.id)
            blocked = _update_problem(values, current, reference)
            if blocked is not None:
                pass  # what the values say is wrong comes before what the catalogue holds
            elif twin is not None:
                blocked = f"portion {twin} already carries '{wanted[1]}' in {wanted[0]}"
            else:
                taken[current.id] = wanted
        else:
            used_by = uow.products.portion_usage(current.id)
            if used_by:
                plural = "" if used_by == 1 else "s"
                blocked = f"still used by {used_by} logged item{plural}, so it cannot be removed"
            else:
                taken.pop(current.id, None)
        rows.append(
            dto.PortionOperationView(
                op=op,
                portion_id=portion_id,
                values=values,
                current=portion_view(current) if current is not None else None,
                used_by=used_by,
                blocked=blocked,
                reason=entry.get("reason"),
            )
        )
    return rows


def _plan_of(uow: UnitOfWork, pr: orm.ProductProposal) -> list[dto.PortionOperationView]:
    """Only a pending proposal has a plan: a decided one has already been applied."""
    changes = pr.changes or {}
    entries = changes.get("portions")
    if not entries or pr.status != PENDING:
        return []
    return portion_plan(
        uow,
        pr.product_id,
        entries,
        reference=_reference_of(_product_of(uow, pr), changes),
    )


def proposal_view(
    pr: orm.ProductProposal,
    product: orm.Product | None,
    plan: list[dto.PortionOperationView] | None = None,
) -> dto.ProductProposalView:
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
        portion_plan=plan or [],
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
        if "portions" in clean:
            clean["portions"] = _validated_portions(clean["portions"])
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
            _assign_capture(cap, run_id)
            uow.audit.record(
                "product.propose", "product", str(p.id), {"proposal": pr.id, "changes": clean}
            )
            uow.flush()
            view = proposal_view(pr, p, _plan_of(uow, pr))
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
            # A product that does not exist yet can only gain portions.
            changes["portions"] = _validated_portions(portions, adds_only=True)
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
            _assign_capture(cap, run_id)
            uow.audit.record(
                "product.propose_new",
                "consumable",
                str(ad.id),
                {"proposal": pr.id, "name": changes["name"]},
            )
            uow.flush()
            view = proposal_view(pr, None, _plan_of(uow, pr))
            uow.commit()
            return view


class ProposeProductVersion(UseCase):
    """Draft "the values changed from this day on"; requires ``agent:write`` (or ``write``).

    An actor that reads a new label can only correct the current version, and that
    rewrites what the days before the change already counted. Approving this instead runs
    ``NewProductVersion``: the version it was drafted against keeps its numbers and its
    days, and the new one starts on ``valid_from`` (R70, R81).
    """

    def execute(
        self,
        product_id: int,
        valid_from: date,
        changes: dict[str, Any],
        *,
        rationale: str | None = None,
        source: str | None = None,
        capture_id: str | None = None,
        run_id: str | None = None,
    ) -> dto.ProductProposalView:
        if not (self.ctx.has_scope(SCOPE_AGENT_WRITE) or self.ctx.has_scope(SCOPE_WRITE)):
            self.ctx.require(SCOPE_AGENT_WRITE)
        # the day is the argument, so it is not one of the fields that changed
        clean = {k: v for k, v in changes.items() if v is not None and k != "valid_from"}
        unknown = sorted(set(clean) - VERSION_FIELDS)
        if unknown:
            raise ValidationFailed(f"fields cannot be proposed: {', '.join(unknown)}")
        if not clean:
            raise ValidationFailed("a new version needs at least one changed field")
        day = _version_day(valid_from)
        with self._uow() as uow:
            previous = uow.products.get(product_id)
            if previous is None:
                raise NotFound(f"product {product_id} not found")
            check_new_version(uow, previous, day)
            cap = uow.captures.get(capture_id) if capture_id else None
            if capture_id and cap is None:
                raise NotFound(f"capture {capture_id} not found")
            pr = uow.proposals.add(
                orm.ProductProposal(
                    tenant_id=self.ctx.tenant_id,
                    product_id=previous.id,
                    kind=VERSION,
                    capture_id=cap.id if cap else None,
                    run_id=run_id,
                    changes={**clean, "valid_from": day.isoformat()},
                    rationale=rationale,
                    source=source,
                    status=PENDING,
                )
            )
            _assign_capture(cap, run_id)
            uow.audit.record(
                "product.propose_version",
                "product",
                str(previous.id),
                {"proposal": pr.id, "valid_from": day.isoformat(), "changes": clean},
            )
            uow.flush()
            view = proposal_view(pr, previous, _plan_of(uow, pr))
            uow.commit()
            return view


class ListProposals(UseCase):
    def execute(
        self, *, status: str | None = PENDING, product_id: int | None = None, limit: int = 200
    ) -> list[dto.ProductProposalView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            rows = uow.proposals.list(status=status, product_id=product_id, limit=limit)
            return [proposal_view(pr, _product_of(uow, pr), _plan_of(uow, pr)) for pr in rows]


class GetProposal(UseCase):
    def execute(self, proposal_id: str) -> dto.ProductProposalView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            pr = uow.proposals.get(proposal_id)
            if pr is None:
                raise NotFound(f"proposal {proposal_id} not found")
            return proposal_view(pr, _product_of(uow, pr), _plan_of(uow, pr))


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
                keep = set(fields)
                if pr.kind == VERSION:
                    # ``valid_from`` is the day the version starts, not one of the values
                    # under review, so a reviewer picking values does not have to name it.
                    keep.add("valid_from")
                applied = {k: v for k, v in applied.items() if k in keep}
            allowed = {NEW: NEW_PRODUCT_FIELDS, VERSION: VERSION_FIELDS}.get(
                pr.kind, PROPOSABLE_FIELDS
            )
            if changes:
                unknown = sorted(set(changes) - allowed)
                if unknown:
                    raise ValidationFailed(f"fields cannot be applied: {', '.join(unknown)}")
                applied.update({k: v for k, v in changes.items() if v is not None})
            if approve and applied.get("portions"):
                applied["portions"] = _validated_portions(
                    applied["portions"], adds_only=pr.kind == NEW
                )
                refused = [
                    f"{row.op} {row.portion_id or row.values.get('unit_code', '')}: {row.blocked}"
                    for row in portion_plan(
                        uow,
                        pr.product_id,
                        applied["portions"],
                        # the values being approved, which may not be the ones proposed
                        reference=_reference_of(_product_of(uow, pr), applied),
                    )
                    if row.blocked
                ]
                if refused:
                    # Nothing is applied yet, so the proposal stays pending and decidable.
                    raise Conflict("; ".join(refused))
            if approve and pr.kind == VERSION:
                previous = _product_of(uow, pr)
                if previous is None:
                    raise NotFound(f"product {pr.product_id} not found")
                # Read while drafting too; the catalogue may have moved on since then.
                check_new_version(uow, previous, _version_day(applied.get("valid_from")))
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
                "consumable" if pr.kind == NEW else "product",
                str(pr.consumable_id if pr.kind == NEW else pr.product_id),
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
        opened: int | None = None  # the version an approved ``version`` proposal created
        if approve:
            apply = dict(applied)
            if source and "source" not in apply:
                apply["source"] = source
            apply["verified"] = True  # a person looked at the label photo and approved it
            if kind == NEW:
                assert consumable_id is not None
                product_id = self._promote(consumable_id, apply)
            elif kind == VERSION:
                assert product_id is not None
                day = _version_day(apply.pop("valid_from", None))
                fresh_version = NewProductVersion(self.uow_factory, self.ctx).execute(
                    product_id, day, apply
                )
                opened = fresh_version.id
            else:
                assert product_id is not None
                portions = apply.pop("portions", None) or []
                UpdateProduct(self.uow_factory, self.ctx).execute(product_id, apply)
                self._apply_portions(product_id, portions)
        with self._uow() as uow:
            fresh = uow.proposals.get(proposal_id)
            assert fresh is not None
            if approve and kind == NEW and fresh.product_id is None:
                fresh.product_id = product_id  # the entry it created, for the review history
                uow.flush()
                uow.commit()
            elif opened is not None:
                # ``product.new_version`` names the row it supersedes, not the proposal that
                # asked for it, so without this the decision and the version it opened are
                # two audit entries with nothing in common.
                uow.audit.record(
                    "product.proposal.version",
                    "product",
                    str(opened),
                    {"proposal": proposal_id, "supersedes": product_id},
                )
                uow.flush()
                uow.commit()
            return proposal_view(fresh, _product_of(uow, fresh), _plan_of(uow, fresh))

    def _apply_portions(self, product_id: int, entries: list[dict[str, Any]]) -> None:
        """Send each entry to the use case its ``op`` names; an entry without one adds."""
        for entry in entries:
            op = _op_of(entry)
            if op == PORTION_UPDATE:
                UpdatePortion(self.uow_factory, self.ctx).execute(
                    int(entry["portion_id"]),
                    {k: entry[k] for k in PORTION_FIELDS if k in entry},
                )
            elif op == PORTION_DELETE:
                DeletePortion(self.uow_factory, self.ctx).execute(int(entry["portion_id"]))
            else:
                AddPortion(self.uow_factory, self.ctx).execute(
                    product_id,
                    PortionInput(
                        unit_code=str(entry["unit_code"]),
                        label=str(entry.get("label") or entry["unit_code"]),
                        amount=float(entry["amount"]),
                        amount_unit=str(entry.get("amount_unit") or "g"),
                        description=entry.get("description"),
                        is_default=bool(entry.get("is_default", False)),
                        weight_source=entry.get("weight_source"),
                    ),
                )

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
        self._apply_portions(product_id, portions)  # a new product's portions are all adds
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
        {"portions": [{**portion, "op": PORTION_ADD}]},
        rationale=rationale,
        capture_id=capture_id,
        run_id=run_id,
    )


def version_or_propose_product_version(
    uow_factory: Any,
    ctx: Any,
    product_id: int,
    valid_from: date,
    changes: dict[str, Any],
    *,
    rationale: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.ProductView | dto.ProductProposalView:
    """Open a new version, or propose one — "the recipe changed on this date".

    Correcting the current version instead is not the same thing: it rewrites what every
    day before the change already counted. That the drafting had no road here while the
    deciding did is exactly what ADR 0013 warns about.
    """
    if ctx.has_scope(SCOPE_APPROVE):
        return NewProductVersion(uow_factory, ctx).execute(product_id, valid_from, changes)
    return ProposeProductVersion(uow_factory, ctx).execute(
        product_id,
        valid_from,
        changes,
        rationale=rationale,
        source=changes.get("source"),
        capture_id=capture_id,
        run_id=run_id,
    )


def _product_of_portion(uow_factory: Any, ctx: Any, portion_id: int) -> int:
    """A portion proposal is filed against the product that owns the portion."""
    ctx.require(SCOPE_READ)
    with uow_factory(ctx) as uow:
        portion = uow.products.get_portion(portion_id)
        if portion is None:
            raise NotFound(f"portion {portion_id} not found")
        return int(portion.product_id)


def update_or_propose_portion(
    uow_factory: Any,
    ctx: Any,
    portion_id: int,
    changes: dict[str, Any],
    *,
    rationale: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.PortionView | dto.ProductProposalView:
    """Correct a portion, or propose the correction — the wrong unit on an existing row.

    Adding the corrected portion instead is not the same thing: the wrong row stays, and
    where the unit is what was wrong the unique ``(product, unit, label)`` refuses it.
    """
    clean = {k: v for k, v in changes.items() if v is not None and k in PORTION_FIELDS}
    if not clean:
        raise ValidationFailed(f"a portion change needs one of: {', '.join(PORTION_FIELDS)}")
    if ctx.has_scope(SCOPE_APPROVE):
        return UpdatePortion(uow_factory, ctx).execute(portion_id, clean)
    return ProposeProductChange(uow_factory, ctx).execute(
        _product_of_portion(uow_factory, ctx, portion_id),
        {"portions": [{"op": PORTION_UPDATE, "portion_id": portion_id, **clean}]},
        rationale=rationale,
        capture_id=capture_id,
        run_id=run_id,
    )


def delete_or_propose_portion(
    uow_factory: Any,
    ctx: Any,
    portion_id: int,
    *,
    reason: str | None = None,
    rationale: str | None = None,
    capture_id: str | None = None,
    run_id: str | None = None,
) -> dto.ProductProposalView | None:
    """Remove a portion, or propose its removal; ``None`` means it is already gone.

    A portion logged days already point at cannot be removed at all. Proposing it stays
    allowed — that a portion is in use is itself worth reporting, and the proposal's plan
    says so — but the approval is refused instead of failing halfway through.
    """
    if ctx.has_scope(SCOPE_APPROVE):
        DeletePortion(uow_factory, ctx).execute(portion_id)
        return None
    return ProposeProductChange(uow_factory, ctx).execute(
        _product_of_portion(uow_factory, ctx, portion_id),
        {"portions": [{"op": PORTION_DELETE, "portion_id": portion_id, "reason": reason}]},
        rationale=rationale,
        capture_id=capture_id,
        run_id=run_id,
    )
