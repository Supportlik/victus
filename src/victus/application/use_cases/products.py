"""Products, portions, categories, units and text matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from victus.application import dto
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UseCase, require_decision
from victus.application.use_cases._mappers import portion_view, product_view
from victus.domain.services.matching import ConsumableIndex
from victus.domain.services.units import UNITS
from victus.domain.values import ConsumableKind, MatchCandidate
from victus.infrastructure.db import orm

PRODUCT_FIELDS = (
    "icon",
    "brand",
    "category_id",
    "reference_amount",
    "reference_unit",
    "density_g_per_ml",
    "kcal",
    "protein",
    "carbs",
    "fat",
    "fiber",
    "salt",
    "source",
    "verified",
    "note",
    "ean",
    "checked_at",
)


@dataclass(frozen=True, slots=True)
class ProductInput:
    name: str
    icon: str | None = None
    brand: str | None = None
    category_id: int | None = None
    category: str | None = None
    reference_amount: float = 100.0
    reference_unit: str = "g"
    density_g_per_ml: float | None = None
    kcal: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None
    fiber: float | None = None
    salt: float | None = None
    source: str | None = None
    verified: bool = False
    note: str | None = None
    ean: str | None = None
    checked_at: date | None = None


@dataclass(frozen=True, slots=True)
class PortionInput:
    unit_code: str
    label: str
    amount: float
    amount_unit: str = "g"
    description: str | None = None
    is_default: bool = False
    weight_source: str | None = None


def _category_names(uow: Any) -> dict[int, str]:
    return {c.id: c.name for c in uow.products.categories()}


def _view(uow: Any, p: orm.Product, names: dict[int, str] | None = None) -> dto.ProductView:
    names = names if names is not None else _category_names(uow)
    return product_view(
        p, uow.products.portions_for(p.id), names.get(p.category_id) if p.category_id else None
    )


def valid_on(versions: list[orm.Product], day: date | None) -> orm.Product | None:
    """The version of a chain that applied on ``day``; without a day, the current one.

    "Current" is the row with no end date, or failing that the one that ended last, so a
    product whose chain has a gap still resolves to something sensible (R70).
    """
    if not versions:
        return None
    if day is not None:
        for p in versions:
            starts_ok = p.valid_from is None or p.valid_from <= day
            ends_ok = p.valid_until is None or p.valid_until >= day
            if starts_ok and ends_ok:
                return p
        return None
    open_ended = [p for p in versions if p.valid_until is None]
    if open_ended:
        return max(open_ended, key=lambda p: (p.valid_from or date.min, p.id))
    return max(versions, key=lambda p: (p.valid_until or date.min, p.id))


def _resolve_versions(uow: Any, rows: list[orm.Product], day: date | None) -> list[orm.Product]:
    """Collapse each version chain to the one row that applied on ``day``.

    Without this a search for a product with three versions would return three rows that
    look identical apart from their numbers.
    """
    out: list[orm.Product] = []
    handled: set[int] = set()
    for p in rows:
        if p.id in handled:
            continue
        chain = list(uow.products.versions_of(p.id))
        handled.update(c.id for c in chain)
        pick = valid_on(chain, day) if len(chain) > 1 else p
        if pick is not None:
            out.append(pick)
        elif day is None:
            out.append(p)
    return out


class SearchProducts(UseCase):
    """Substring search first; when it finds little, the fuzzy matcher adds candidates."""

    def execute(
        self,
        query: str,
        *,
        category_id: int | None = None,
        limit: int = 20,
        on: date | None = None,
    ) -> list[dto.ProductView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            names = _category_names(uow)
            if not query.strip():
                rows = _resolve_versions(uow, list(uow.products.list(category_id=category_id)), on)
                return [_view(uow, p, names) for p in rows[:limit]]
            rows = list(uow.products.search(query, limit=limit))
            if category_id is not None:
                rows = [p for p in rows if p.category_id == category_id]
            if len(rows) < 3:
                index = ConsumableIndex(
                    (cid, ConsumableKind.PRODUCT, name) for cid, name in uow.products.all_names()
                )
                seen = {p.id for p in rows}
                for cand in index.find(query, limit=limit):
                    if cand.consumable_id in seen:
                        continue
                    p = uow.products.get(cand.consumable_id)
                    if p is not None and (category_id is None or p.category_id == category_id):
                        rows.append(p)
                        seen.add(p.id)
            rows = _resolve_versions(uow, rows, on)
            return [_view(uow, p, names) for p in rows[:limit]]


class ProductVersions(UseCase):
    """Every version of a product, oldest first, so the history is visible (R70)."""

    def execute(self, product_id: int) -> list[dto.ProductView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            if uow.products.get(product_id) is None:
                raise NotFound(f"product {product_id} not found")
            names = _category_names(uow)
            return [_view(uow, p, names) for p in uow.products.versions_of(product_id)]


class NewProductVersion(UseCase):
    """Record that a product's values changed from a given day.

    The previous version keeps its numbers and is closed the day before, so every day
    already logged still shows what was eaten. The new row starts open ended, which is
    what "still valid" means: nothing has to be maintained later (R70).
    """

    def execute(
        self, product_id: int, valid_from: date, changes: dict[str, Any] | None = None
    ) -> dto.ProductView:
        require_decision(self.ctx)  # new values for a product are a person's call (R54)
        with self._uow() as uow:
            previous = uow.products.get(product_id)
            if previous is None:
                raise NotFound(f"product {product_id} not found")
            if previous.valid_from is not None and valid_from <= previous.valid_from:
                raise ValidationFailed(
                    f"the new version must start after {previous.valid_from.isoformat()}, "
                    "when the one it replaces began"
                )
            chain = list(uow.products.versions_of(product_id))
            successor = next((p for p in chain if p.supersedes_id == previous.id), None)
            if successor is not None:
                # the history stays a line, not a tree: continue from the newest version
                raise Conflict(
                    f"product {previous.id} was already replaced by {successor.id}; "
                    "create the new version from that one"
                )

            fields = {k: getattr(previous, k) for k in PRODUCT_FIELDS if k != "name"}
            fields["category_id"] = previous.category_id
            name = previous.name
            for key, value in (changes or {}).items():
                if key == "name":
                    name = str(value).strip() or name
                elif key == "category" and value:
                    fields["category_id"] = _resolve_category(
                        uow, ProductInput(name="x", category=str(value))
                    )
                elif key in PRODUCT_FIELDS:
                    fields[key] = value
            fields["valid_from"] = valid_from
            fields["valid_until"] = None
            fields["supersedes_id"] = previous.id
            fresh = uow.products.add_product(name, **fields)

            # close the old one the day before, unless it already ends earlier
            end = valid_from - timedelta(days=1)
            if previous.valid_until is None or previous.valid_until > end:
                previous.valid_until = end

            for portion in uow.products.portions_for(previous.id):
                uow.products.add_portion(
                    orm.Portion(
                        product_id=fresh.id,
                        unit_code=portion.unit_code,
                        label=portion.label,
                        amount=portion.amount,
                        amount_unit=portion.amount_unit,
                        description=portion.description,
                        is_default=portion.is_default,
                        weight_source=portion.weight_source,
                    )
                )
            uow.audit.record(
                "product.new_version",
                "product",
                str(fresh.id),
                {"supersedes": previous.id, "valid_from": valid_from.isoformat()},
            )
            uow.flush()
            view = _view(uow, fresh)
            uow.commit()
            return view


class GetProduct(UseCase):
    def execute(self, product_id: int) -> dto.ProductView:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            p = uow.products.get(product_id)
            if p is None:
                raise NotFound(f"product {product_id} not found")
            return _view(uow, p)


def _resolve_category(uow: Any, data: ProductInput) -> int | None:
    if data.category_id is not None:
        return data.category_id
    if data.category:
        cat = uow.products.category_by_name(data.category)
        if cat is None:
            cat = uow.products.add_category(
                orm.Category(tenant_id=uow.ctx.tenant_id, name=data.category)
            )
        return int(cat.id)
    return None


def _validate_product(data: ProductInput) -> None:
    if not data.name.strip():
        raise ValidationFailed(
            "name is required", errors=[{"field": "name", "message": "required"}]
        )
    if data.reference_unit not in ("g", "ml"):
        raise ValidationFailed("reference_unit must be g or ml")
    if data.reference_amount <= 0:
        raise ValidationFailed("reference_amount must be positive")


class GetProductUsage(UseCase):
    """Which days a product was logged on, newest first."""

    def execute(self, product_id: int, *, limit: int = 100) -> dto.ProductUsage:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            if uow.products.get_consumable(product_id) is None:
                raise NotFound(f"product {product_id} not found")
            rows = uow.day_logs.usage_of(product_id, limit=limit)
            entries = [
                dto.ProductUsageEntry(
                    date=r["date"]
                    if isinstance(r["date"], date)
                    else date.fromisoformat(str(r["date"])),
                    day_status=str(r["day_status"]),
                    meal=str(r["meal"] or ""),
                    line_item_id=int(r["line_item_id"]),
                    amount=float(r["amount"]) if r["amount"] is not None else None,
                    unit_code=str(r["unit_code"]) if r["unit_code"] else None,
                    base_amount=float(r["base_amount"]),
                    base_unit=str(r["base_unit"]),
                    is_draft=bool(r["is_draft"]),
                    estimated=bool(r["estimated"]) or bool(r["amount_estimated"]),
                    kcal=float(r["kcal"]) if r["kcal"] is not None else None,
                    protein=float(r["protein"]) if r["protein"] is not None else None,
                )
                for r in rows
            ]
            dates = [e.date for e in entries]
            return dto.ProductUsage(
                product_id=product_id,
                entries=entries,
                days=len({e.date for e in entries}),
                total_base_amount=sum(e.base_amount for e in entries),
                total_kcal=sum(e.kcal or 0.0 for e in entries),
                first_date=min(dates) if dates else None,
                last_date=max(dates) if dates else None,
            )


class CreateProduct(UseCase):
    """Write a catalogue entry. Needs ``approve``; without it use ``ProposeNewProduct``."""

    def execute(self, data: ProductInput) -> dto.ProductView:
        require_decision(self.ctx)
        _validate_product(data)
        with self._uow() as uow:
            if uow.products.by_name(data.name) is not None:
                raise Conflict(
                    f"product '{data.name}' already exists; to record changed values use "
                    "a new version of it instead"
                )
            fields = {k: getattr(data, k) for k in PRODUCT_FIELDS}
            fields["category_id"] = _resolve_category(uow, data)
            p = uow.products.add_product(data.name.strip(), **fields)
            uow.audit.record("product.create", "product", str(p.id), {"name": data.name})
            view = _view(uow, p)
            uow.commit()
            return view


class UpdateProduct(UseCase):
    """Write product values. Needs ``approve``; without it use ``ProposeProductChange``."""

    def execute(self, product_id: int, changes: dict[str, Any]) -> dto.ProductView:
        require_decision(self.ctx)
        with self._uow() as uow:
            p = uow.products.get(product_id)
            if p is None:
                raise NotFound(f"product {product_id} not found")
            diff: dict[str, Any] = {}
            if changes.get("name"):
                other = uow.products.by_name(changes["name"])
                if other is not None and other.id != p.id:
                    raise Conflict(f"product '{changes['name']}' already exists")
                p.consumable.name = changes["name"].strip()
                diff["name"] = changes["name"]
            if "category" in changes and changes["category"] and "category_id" not in changes:
                changes = {
                    **changes,
                    "category_id": _resolve_category(
                        uow, ProductInput(name="x", category=changes["category"])
                    ),
                }
            for key in PRODUCT_FIELDS:
                if key in changes:
                    setattr(p, key, changes[key])
                    diff[key] = changes[key]
            if p.reference_unit not in ("g", "ml") or p.reference_amount <= 0:
                raise ValidationFailed("invalid reference amount/unit")
            uow.audit.record("product.update", "product", str(p.id), diff)
            uow.flush()
            view = _view(uow, p)
            uow.commit()
            return view


class DeleteProduct(UseCase):
    def execute(self, product_id: int) -> None:
        require_decision(self.ctx)
        with self._uow() as uow:
            p = uow.products.get(product_id)
            if p is None:
                raise NotFound(f"product {product_id} not found")
            consumable = uow.products.get_consumable(p.id)
            try:
                uow.audit.record("product.delete", "product", str(p.id), {"name": p.name})
                if consumable is not None:
                    uow.products.delete_consumable(consumable)
                uow.commit()
            except Exception as exc:  # RESTRICT: still referenced by line items / ingredients
                uow.rollback()
                raise Conflict("product is referenced by line items or recipes") from exc


def _check_portion_unit(product: orm.Product, amount_unit: str) -> None:
    """A portion must be measured the way the product's nutrients are (R75).

    Nutrients are stated per reference amount in grams or millilitres. A portion given in
    the other unit cannot be converted without a density, so the numbers it produces would
    be wrong rather than merely imprecise.
    """
    if amount_unit == product.reference_unit:
        return
    if product.density_g_per_ml:
        return
    raise ValidationFailed(
        f"this product's values are per {product.reference_amount:g} "
        f"{product.reference_unit}, so a portion must be in {product.reference_unit}. "
        f"Set a density to allow {amount_unit}."
    )


class AddPortion(UseCase):
    def execute(self, product_id: int, data: PortionInput) -> dto.PortionView:
        require_decision(self.ctx)
        if data.unit_code not in UNITS:
            raise ValidationFailed(f"unknown unit '{data.unit_code}'")
        if data.amount <= 0 or data.amount_unit not in ("g", "ml"):
            raise ValidationFailed("portion amount must be positive, unit g or ml")
        with self._uow() as uow:
            product = uow.products.get(product_id)
            if product is None:
                raise NotFound(f"product {product_id} not found")
            _check_portion_unit(product, data.amount_unit)
            if data.is_default:
                for existing in uow.products.portions_for(product_id):
                    if existing.unit_code == data.unit_code and existing.is_default:
                        existing.is_default = False
            portion = uow.products.add_portion(
                orm.Portion(
                    product_id=product_id,
                    unit_code=data.unit_code,
                    label=data.label,
                    description=data.description,
                    amount=data.amount,
                    amount_unit=data.amount_unit,
                    is_default=data.is_default,
                    weight_source=data.weight_source,
                )
            )
            view = portion_view(portion)
            uow.commit()
            return view


class UpdatePortion(UseCase):
    def execute(self, portion_id: int, changes: dict[str, Any]) -> dto.PortionView:
        require_decision(self.ctx)
        with self._uow() as uow:
            portion = uow.products.get_portion(portion_id)
            if portion is None:
                raise NotFound(f"portion {portion_id} not found")
            for key in (
                "unit_code",
                "label",
                "description",
                "amount",
                "amount_unit",
                "weight_source",
            ):
                if key in changes and changes[key] is not None:
                    setattr(portion, key, changes[key])
            product = uow.products.get(portion.product_id)
            if product is not None:
                _check_portion_unit(product, portion.amount_unit)
            if changes.get("is_default"):
                for other in uow.products.portions_for(portion.product_id):
                    if other.id != portion.id and other.unit_code == portion.unit_code:
                        other.is_default = False
                portion.is_default = True
            elif "is_default" in changes and changes["is_default"] is False:
                portion.is_default = False
            uow.flush()
            view = portion_view(portion)
            uow.commit()
            return view


class DeletePortion(UseCase):
    def execute(self, portion_id: int) -> None:
        require_decision(self.ctx)
        with self._uow() as uow:
            portion = uow.products.get_portion(portion_id)
            if portion is None:
                raise NotFound(f"portion {portion_id} not found")
            try:
                uow.products.delete_portion(portion)
                uow.commit()
            except Exception as exc:
                uow.rollback()
                raise Conflict("portion is referenced by line items") from exc


class ListCategories(UseCase):
    def execute(self) -> list[dto.CategoryView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [dto.CategoryView(c.id, c.name) for c in uow.products.categories()]


class CreateCategory(UseCase):
    def execute(self, name: str) -> dto.CategoryView:
        self.ctx.require(SCOPE_WRITE)
        with self._uow() as uow:
            if uow.products.category_by_name(name) is not None:
                raise Conflict(f"category '{name}' exists")
            c = uow.products.add_category(orm.Category(tenant_id=self.ctx.tenant_id, name=name))
            view = dto.CategoryView(c.id, c.name)
            uow.commit()
            return view


class ListUnits(UseCase):
    def execute(self) -> list[dto.UnitView]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            return [
                dto.UnitView(u.code, u.singular, u.plural, u.unit_type)
                for u in uow.products.units()
            ]


class MatchText(UseCase):
    """Candidates for a free-text item, the same function the agent and the review list use."""

    def execute(self, text: str, limit: int = 5) -> list[MatchCandidate]:
        self.ctx.require(SCOPE_READ)
        with self._uow() as uow:
            entries = [
                (cid, ConsumableKind.PRODUCT, name) for cid, name in uow.products.all_names()
            ]
            for recipe in uow.recipes.list():
                for batch in uow.recipes.batches_for(recipe.id):
                    entries.append((batch.id, ConsumableKind.RECIPE_BATCH, batch.name))
            return ConsumableIndex(entries).find(text, limit=limit)
