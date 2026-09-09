"""ORM → view / domain conversions shared by the use cases."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from victus.application import dto
from victus.domain.values import Band, Macros, TargetBand, TrainingType
from victus.infrastructure.db import orm

MACROS = ("kcal", "protein", "carbs", "fat", "fiber", "salt")


def portion_view(p: orm.Portion) -> dto.PortionView:
    return dto.PortionView(
        id=p.id,
        product_id=p.product_id,
        unit_code=p.unit_code,
        label=p.label,
        description=p.description,
        amount=p.amount,
        amount_unit=p.amount_unit,
        is_default=bool(p.is_default),
        weight_source=p.weight_source,
    )


def product_view(
    p: orm.Product, portions: Iterable[orm.Portion] = (), category_name: str | None = None
) -> dto.ProductView:
    return dto.ProductView(
        id=p.id,
        name=p.name,
        icon=p.icon,
        brand=p.brand,
        category_id=p.category_id,
        category=category_name,
        reference_amount=p.reference_amount,
        reference_unit=p.reference_unit,
        kcal=p.kcal,
        protein=p.protein,
        carbs=p.carbs,
        fat=p.fat,
        fiber=p.fiber,
        salt=p.salt,
        source=p.source,
        verified=bool(p.verified),
        ean=p.ean,
        note=p.note,
        valid_from=p.valid_from,
        valid_until=p.valid_until,
        supersedes_id=p.supersedes_id,
        portions=[portion_view(x) for x in portions],
    )


def product_macros(p: orm.Product | orm.AdHocItem) -> Macros:
    return Macros(
        kcal=p.kcal, protein=p.protein, carbs=p.carbs, fat=p.fat, fiber=p.fiber, salt=p.salt
    )


def batch_view(b: orm.RecipeBatch) -> dto.BatchView:
    return dto.BatchView(
        id=b.id,
        recipe_id=b.recipe_id,
        name=b.name,
        cooked_at=b.cooked_at,
        servings=b.servings,
        total_weight_g=b.total_weight_g,
        kcal=b.kcal_total,
        protein=b.protein_total,
        carbs=b.carbs_total,
        fat=b.fat_total,
        fiber=b.fiber_total,
        salt=b.salt_total,
        finished_at=b.finished_at,
    )


def recipe_view(
    r: orm.Recipe,
    batches: Iterable[orm.RecipeBatch] = (),
    product_names: dict[int, str] | None = None,
) -> dto.RecipeView:
    names = product_names or {}
    return dto.RecipeView(
        id=r.id,
        name=r.name,
        default_servings=r.default_servings,
        ingredients=[
            dto.IngredientView(
                id=i.id,
                position=i.position,
                product_id=i.product_id,
                product_name=names.get(i.product_id) if i.product_id else None,
                amount=i.amount,
                unit_code=i.unit_code,
                free_text=i.free_text,
            )
            for i in r.ingredients
        ],
        batches=[batch_view(b) for b in batches],
    )


def _band(tb: orm.TargetBand, prefix: str) -> Band | None:
    vals = [getattr(tb, f"{prefix}_{k}") for k in ("min", "opt_min", "opt_max", "target", "max")]
    if any(v is None for v in vals):
        return None
    stretch = getattr(tb, f"{prefix}_stretch", None)
    return Band(
        min=float(vals[0]),
        opt_min=float(vals[1]),
        opt_max=float(vals[2]),
        target=float(vals[3]),
        max=float(vals[4]),
        stretch=float(stretch) if stretch is not None else None,
    )


def band_spec_view(b: Band | None) -> dto.BandSpecView | None:
    if b is None:
        return None
    return dto.BandSpecView(b.min, b.opt_min, b.opt_max, b.target, b.max, b.stretch)


def target_band_domain(tb: orm.TargetBand) -> TargetBand | None:
    bands = {k: _band(tb, k) for k in ("protein", "carbs", "fat", "fiber", "salt")}
    if any(v is None for v in bands.values()):
        return None
    return TargetBand(
        name=tb.name,
        training_type=TrainingType(tb.training_type) if tb.training_type else None,
        valid_from=tb.valid_from,
        valid_until=tb.valid_until,
        protein=bands["protein"],  # type: ignore[arg-type]
        carbs=bands["carbs"],  # type: ignore[arg-type]
        fat=bands["fat"],  # type: ignore[arg-type]
        fiber=bands["fiber"],  # type: ignore[arg-type]
        salt=bands["salt"],  # type: ignore[arg-type]
        kcal=_band(tb, "kcal"),
    )


def target_band_view(tb: orm.TargetBand) -> dto.TargetBandView:
    def spec(prefix: str) -> dto.BandSpecView:
        b = _band(tb, prefix)
        if b is None:
            return dto.BandSpecView(0, 0, 0, 0, 0, None)
        return band_spec_view(b) or dto.BandSpecView(0, 0, 0, 0, 0, None)

    return dto.TargetBandView(
        id=tb.id,
        name=tb.name,
        training_type=tb.training_type,
        valid_from=tb.valid_from,
        valid_until=tb.valid_until,
        kcal=band_spec_view(_band(tb, "kcal")),
        protein=spec("protein"),
        carbs=spec("carbs"),
        fat=spec("fat"),
        fiber=spec("fiber"),
        salt=spec("salt"),
        note=tb.note,
    )


def line_item_view(
    li: orm.LineItem,
    macros: Macros | None,
    consumable: orm.Consumable | None,
    category: str | None = None,
    icon: str | None = None,
) -> dto.LineItemView:
    m = macros or Macros()
    return dto.LineItemView(
        id=li.id,
        meal_id=li.meal_id,
        position=li.position,
        consumable_id=li.consumable_id,
        consumable_name=consumable.name if consumable else "",
        consumable_kind=consumable.kind if consumable else "product",
        amount=li.amount,
        unit_code=li.unit_code,
        base_amount=li.base_amount,
        base_unit=li.base_unit,
        estimated=bool(li.estimated),
        amount_estimated=bool(li.amount_estimated),
        is_draft=bool(li.is_draft),
        confidence=li.confidence,
        rationale=li.rationale,
        alternatives=li.alternatives,
        raw_text=li.raw_text,
        source_capture_id=li.source_capture_id,
        source_kind=li.source_kind,
        category=category,
        icon=icon,
        kcal=m.kcal,
        protein=m.protein,
        carbs=m.carbs,
        fat=m.fat,
        fiber=m.fiber,
        salt=m.salt,
    )


def weekday_name(day: date) -> str:
    return day.strftime("%A")
