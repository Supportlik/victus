"""Products, portions, categories, units, recipes and batches."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo, normalize


class ProductRepo(Repo):
    # ── consumables / products ──
    def get(self, product_id: int) -> orm.Product | None:
        stmt = (
            select(orm.Product)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(orm.Product.id == product_id, orm.Consumable.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)

    def get_consumable(self, consumable_id: int) -> orm.Consumable | None:
        return self.session.scalar(
            self.scoped(
                select(orm.Consumable).where(orm.Consumable.id == consumable_id), orm.Consumable
            )
        )

    def add(self, product: orm.Product) -> orm.Product:
        """Add a prepared product row; prefer ``add_product`` to create supertype + product."""
        self.session.add(product)
        self.session.flush()
        return product

    def add_product(self, name: str, **fields: object) -> orm.Product:
        """Create supertype row + product row in one go."""
        consumable = orm.Consumable(tenant_id=self.tenant_id, kind="product", name=name)
        self.session.add(consumable)
        self.session.flush()
        product = orm.Product(id=consumable.id, kind="product", **fields)
        self.session.add(product)
        self.session.flush()
        return product

    def add_ad_hoc(self, item: orm.AdHocItem) -> orm.AdHocItem:
        self.session.add(item)
        self.session.flush()
        return item

    def add_ad_hoc_item(self, name: str, **fields: object) -> orm.AdHocItem:
        consumable = orm.Consumable(tenant_id=self.tenant_id, kind="ad_hoc", name=name)
        self.session.add(consumable)
        self.session.flush()
        item = orm.AdHocItem(id=consumable.id, kind="ad_hoc", **fields)
        self.session.add(item)
        self.session.flush()
        return item

    def list(self, *, category_id: int | None = None) -> Sequence[orm.Product]:
        stmt = (
            select(orm.Product)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(orm.Consumable.tenant_id == self.tenant_id)
            .order_by(orm.Consumable.name)
        )
        if category_id is not None:
            stmt = stmt.where(orm.Product.category_id == category_id)
        return self.session.scalars(stmt).all()

    def search(self, query: str, limit: int = 20) -> Sequence[orm.Product]:
        """Case-insensitive substring search over name and brand (all words must match)."""
        words = [w for w in normalize(query).split(" ") if w]
        stmt = (
            select(orm.Product)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(orm.Consumable.tenant_id == self.tenant_id)
        )
        for w in words:
            like = f"%{w}%"
            stmt = stmt.where(
                or_(
                    func.lower(orm.Consumable.name).like(like),
                    func.lower(orm.Product.brand).like(like),
                )
            )
        return self.session.scalars(stmt.order_by(orm.Consumable.name).limit(limit)).all()

    def by_external_ref(self, external_ref: str) -> orm.Product | None:
        stmt = (
            select(orm.Product)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(
                orm.Product.external_ref == external_ref, orm.Consumable.tenant_id == self.tenant_id
            )
        )
        return self.session.scalar(stmt)

    def by_name(self, name: str) -> orm.Product | None:
        stmt = (
            select(orm.Product)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(orm.Consumable.name == name, orm.Consumable.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)

    def all_names(self) -> Sequence[tuple[int, str]]:
        stmt = self.scoped(
            select(orm.Consumable.id, orm.Consumable.name).where(orm.Consumable.kind == "product"),
            orm.Consumable,
        )
        return [(int(i), str(n)) for i, n in self.session.execute(stmt).all()]

    # ── portions ──
    def portions_for(self, product_id: int) -> Sequence[orm.Portion]:
        if self.get(product_id) is None:
            return []
        return self.session.scalars(
            select(orm.Portion).where(orm.Portion.product_id == product_id).order_by(orm.Portion.id)
        ).all()

    def add_portion(self, portion: orm.Portion) -> orm.Portion:
        if self.get(portion.product_id) is None:
            raise PermissionError("product not in tenant")
        self.session.add(portion)
        self.session.flush()
        return portion

    def get_portion(self, portion_id: int) -> orm.Portion | None:
        stmt = (
            select(orm.Portion)
            .join(orm.Product, orm.Product.id == orm.Portion.product_id)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .where(orm.Portion.id == portion_id, orm.Consumable.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)

    def delete_portion(self, portion: orm.Portion) -> None:
        if self.get_portion(portion.id) is None:
            raise PermissionError("portion not in tenant")
        self.session.delete(portion)
        self.session.flush()

    def delete_consumable(self, consumable: orm.Consumable) -> None:
        """Delete a consumable and its subtype row (FK cascade). RESTRICT on use raises."""
        self.guard(consumable)
        self.session.delete(consumable)
        self.session.flush()

    # ── categories ──
    def display_hints_for(
        self, product_ids: Sequence[int]
    ) -> dict[int, tuple[str | None, str | None]]:
        """{product id: (category name, icon)} for the given products, in one query."""
        if not product_ids:
            return {}
        stmt = (
            select(orm.Product.id, orm.Category.name, orm.Product.icon)
            .join(orm.Consumable, orm.Consumable.id == orm.Product.id)
            .outerjoin(orm.Category, orm.Category.id == orm.Product.category_id)
            .where(orm.Consumable.tenant_id == self.tenant_id, orm.Product.id.in_(product_ids))
        )
        return {
            int(i): (str(n) if n is not None else None, str(ic) if ic else None)
            for i, n, ic in self.session.execute(stmt).all()
        }

    def category_names_for(self, product_ids: Sequence[int]) -> dict[int, str]:
        """{product id: category name} for the given products."""
        return {
            pid: name for pid, (name, _icon) in self.display_hints_for(product_ids).items() if name
        }

    def categories(self) -> Sequence[orm.Category]:
        return self.session.scalars(
            self.scoped(select(orm.Category), orm.Category).order_by(
                orm.Category.sort_order, orm.Category.name
            )
        ).all()

    def category_by_name(self, name: str) -> orm.Category | None:
        return self.session.scalar(
            self.scoped(select(orm.Category).where(orm.Category.name == name), orm.Category)
        )

    def add_category(self, category: orm.Category) -> orm.Category:
        self.guard(category)
        self.session.add(category)
        self.session.flush()
        return category

    # ── units (global) ──
    def units(self) -> Sequence[orm.Unit]:
        return self.session.scalars(select(orm.Unit).order_by(orm.Unit.code)).all()

    def unit(self, code: str) -> orm.Unit | None:
        return self.session.get(orm.Unit, code)


class RecipeRepo(Repo):
    def get(self, recipe_id: int) -> orm.Recipe | None:
        return self.session.scalar(
            self.scoped(select(orm.Recipe).where(orm.Recipe.id == recipe_id), orm.Recipe)
        )

    def by_name(self, name: str) -> orm.Recipe | None:
        return self.session.scalar(
            self.scoped(select(orm.Recipe).where(orm.Recipe.name == name), orm.Recipe)
        )

    def add(self, recipe: orm.Recipe) -> orm.Recipe:
        self.guard(recipe)
        self.session.add(recipe)
        self.session.flush()
        return recipe

    def list(self) -> Sequence[orm.Recipe]:
        return self.session.scalars(
            self.scoped(select(orm.Recipe), orm.Recipe).order_by(orm.Recipe.name)
        ).all()

    def add_batch(self, batch: orm.RecipeBatch) -> orm.RecipeBatch:
        self.session.add(batch)
        self.session.flush()
        return batch

    def add_recipe_batch(self, recipe: orm.Recipe, name: str, **fields: object) -> orm.RecipeBatch:
        """Create supertype row + batch row for a recipe of this tenant."""
        if recipe.tenant_id != self.tenant_id:
            raise PermissionError("recipe not in tenant")
        consumable = orm.Consumable(tenant_id=self.tenant_id, kind="recipe_batch", name=name)
        self.session.add(consumable)
        self.session.flush()
        batch = orm.RecipeBatch(
            id=consumable.id, kind="recipe_batch", recipe_id=recipe.id, **fields
        )
        self.session.add(batch)
        self.session.flush()
        return batch

    def batches_for(self, recipe_id: int) -> Sequence[orm.RecipeBatch]:
        if self.get(recipe_id) is None:
            return []
        return self.session.scalars(
            select(orm.RecipeBatch)
            .where(orm.RecipeBatch.recipe_id == recipe_id)
            .order_by(orm.RecipeBatch.id)
        ).all()

    def get_batch(self, batch_id: int) -> orm.RecipeBatch | None:
        stmt = (
            select(orm.RecipeBatch)
            .join(orm.Consumable, orm.Consumable.id == orm.RecipeBatch.id)
            .where(orm.RecipeBatch.id == batch_id, orm.Consumable.tenant_id == self.tenant_id)
        )
        return self.session.scalar(stmt)
