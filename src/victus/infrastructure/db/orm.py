"""SQLAlchemy 2.x mapped models — the persistence schema of Victus.

Dialect-neutral (SQLite and PostgreSQL): string columns with CHECK constraints
instead of database enums, ``JSON`` for structured payloads, timezone-aware
timestamps in UTC. Every business table carries an indexed ``tenant_id``.

Design rules carried over from the predecessor schema (see ``docs/SPEC.md``):

* nutrients are stored only on ``product``, ``recipe_batch`` and ``ad_hoc_item``
  — never on ``line_item``; the views in ``views.py`` compute them;
* ``line_item.base_amount`` is frozen at logging time;
* ``consumable`` is the supertype; ``UNIQUE(id, kind)`` lets the subtypes carry a
  composite foreign key so a batch cannot masquerade as a product;
* ``day_log.reliable`` has **no default** — NULL is an error the checks report.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from victus.infrastructure.db.ids import new_id


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON, list[Any]: JSON}


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC timestamps on every dialect.

    PostgreSQL stores and returns aware values natively; SQLite has no notion of
    time zones and hands back naive values, which would make comparisons with
    aware Python datetimes fail. Bind values are normalised to UTC, result
    values are re-attached to UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


ID = String(32)
TS = UTCDateTime()


# ── Tenancy and authentication ──────────────────────────────────────────────


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("role IN ('owner','member')", name="ck_user_role"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    recovery_code_hash: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class PasskeyCredential(Base):
    __tablename__ = "passkey_credential"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aaguid: Mapped[str | None] = mapped_column(String(36))
    transports: Mapped[list[Any] | None] = mapped_column(JSON)
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(500))


class ApiToken(Base):
    __tablename__ = "api_token"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("user.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    last_used_at: Mapped[datetime | None] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class TenantSettings(Base):
    __tablename__ = "tenant_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


# ── Master data ─────────────────────────────────────────────────────────────


class Unit(Base):
    """Global unit master data (no tenant)."""

    __tablename__ = "unit"
    __table_args__ = (
        CheckConstraint("unit_type IN ('mass','volume','count')", name="ck_unit_type"),
        CheckConstraint(
            "(unit_type IN ('mass','volume') AND factor_base IS NOT NULL AND needs_portion = 0)"
            " OR (unit_type = 'count' AND needs_portion = 1)",
            name="ck_unit_consistency",
        ),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    singular: Mapped[str] = mapped_column(String(64), nullable=False)
    plural: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    factor_base: Mapped[float | None] = mapped_column(Float)
    needs_portion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fuzzy: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ── Consumable supertype and subtypes ───────────────────────────────────────


class Consumable(Base):
    __tablename__ = "consumable"
    __table_args__ = (
        CheckConstraint("kind IN ('product','recipe_batch','ad_hoc')", name="ck_consumable_kind"),
        UniqueConstraint("id", "kind", name="uq_consumable_id_kind"),
        Index("ix_consumable_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "kind"], ["consumable.id", "consumable.kind"], ondelete="CASCADE"
        ),
        CheckConstraint("kind = 'product'", name="ck_product_kind"),
        CheckConstraint("reference_unit IN ('g','ml')", name="ck_product_reference_unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="product")
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    brand: Mapped[str | None] = mapped_column(String(200))
    reference_amount: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    reference_unit: Mapped[str] = mapped_column(String(2), nullable=False, default="g")
    density_g_per_ml: Mapped[float | None] = mapped_column(Float)
    #: one or two characters shown in front of the item; overrides the guessed glyph
    icon: Mapped[str | None] = mapped_column(String(8))
    kcal: Mapped[float | None] = mapped_column(Float)
    protein: Mapped[float | None] = mapped_column(Float)
    carbs: Mapped[float | None] = mapped_column(Float)
    fat: Mapped[float | None] = mapped_column(Float)
    fiber: Mapped[float | None] = mapped_column(Float)
    salt: Mapped[float | None] = mapped_column(Float)  # NULL = not declared (≠ 0)
    source: Mapped[str | None] = mapped_column(String(500))
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    ean: Mapped[str | None] = mapped_column(String(14))
    checked_at: Mapped[date | None] = mapped_column(Date)
    external_ref: Mapped[str | None] = mapped_column(String(200), index=True)
    #: First day these values applied. NULL reaches as far back as the data goes.
    valid_from: Mapped[date | None] = mapped_column(Date)
    #: Last day they applied. NULL means the product is simply current (R70).
    valid_until: Mapped[date | None] = mapped_column(Date)
    #: The version this one replaces, so the history reads in both directions.
    supersedes_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TS, nullable=False, default=utcnow, onupdate=utcnow
    )

    consumable: Mapped[Consumable] = relationship(
        primaryjoin="Product.id == foreign(Consumable.id)", uselist=False, viewonly=True
    )
    portions: Mapped[list[Portion]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    @property
    def name(self) -> str:
        return self.consumable.name


class Portion(Base):
    """The only place where piece weights live."""

    __tablename__ = "portion"
    __table_args__ = (
        UniqueConstraint("product_id", "unit_code", "label"),
        CheckConstraint("amount_unit IN ('g','ml')", name="ck_portion_amount_unit"),
        CheckConstraint(
            "weight_source IN ('weighed','estimated') OR weight_source IS NULL",
            name="ck_portion_ws",
        ),
        Index(
            "ux_portion_default",
            "product_id",
            "unit_code",
            unique=True,
            sqlite_where=text("is_default = 1"),
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="CASCADE"), nullable=False
    )
    unit_code: Mapped[str] = mapped_column(String(32), ForeignKey("unit.code"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    amount: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # suggestion, not calculation basis
    amount_unit: Mapped[str] = mapped_column(String(2), nullable=False, default="g")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight_source: Mapped[str | None] = mapped_column(String(16))
    changed_at: Mapped[datetime | None] = mapped_column(TS)

    product: Mapped[Product] = relationship(back_populates="portions")


class Recipe(Base):
    __tablename__ = "recipe"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(300))
    default_servings: Mapped[int | None] = mapped_column(Integer)
    first_cooked_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    ingredients: Mapped[list[RecipeIngredient]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.position"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredient"
    __table_args__ = (
        CheckConstraint("base_unit IN ('g','ml') OR base_unit IS NULL", name="ck_ri_base_unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="RESTRICT")
    )
    portion_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("portion.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("unit.code"))
    amount: Mapped[float | None] = mapped_column(Float)
    base_amount: Mapped[float | None] = mapped_column(Float)  # frozen
    base_unit: Mapped[str | None] = mapped_column(String(2))
    amount_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    free_text: Mapped[str | None] = mapped_column(String(300))

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class RecipeBatch(Base):
    """One cooking event; totals are frozen when cooked."""

    __tablename__ = "recipe_batch"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "kind"], ["consumable.id", "consumable.kind"], ondelete="CASCADE"
        ),
        CheckConstraint("kind = 'recipe_batch'", name="ck_batch_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="recipe_batch")
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="RESTRICT"), nullable=False
    )
    cooked_at: Mapped[date | None] = mapped_column(Date)  # NULL = "unknown batch" (legacy logs)
    servings: Mapped[int | None] = mapped_column(Integer)
    total_weight_g: Mapped[float | None] = mapped_column(Float)
    kcal_total: Mapped[float | None] = mapped_column(Float)
    protein_total: Mapped[float | None] = mapped_column(Float)
    carbs_total: Mapped[float | None] = mapped_column(Float)
    fat_total: Mapped[float | None] = mapped_column(Float)
    fiber_total: Mapped[float | None] = mapped_column(Float)
    salt_total: Mapped[float | None] = mapped_column(Float)
    finished_at: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)

    consumable: Mapped[Consumable] = relationship(
        primaryjoin="RecipeBatch.id == foreign(Consumable.id)", uselist=False, viewonly=True
    )
    recipe: Mapped[Recipe] = relationship()

    @property
    def name(self) -> str:
        return self.consumable.name


class AdHocItem(Base):
    """One-off items (restaurant meals, unmatched import rows)."""

    __tablename__ = "ad_hoc_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "kind"], ["consumable.id", "consumable.kind"], ondelete="CASCADE"
        ),
        CheckConstraint("kind = 'ad_hoc'", name="ck_ad_hoc_kind"),
        CheckConstraint("reference_unit IN ('g','ml')", name="ck_ad_hoc_reference_unit"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ad_hoc")
    reference_amount: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    reference_unit: Mapped[str] = mapped_column(String(2), nullable=False, default="g")
    kcal: Mapped[float | None] = mapped_column(Float)
    protein: Mapped[float | None] = mapped_column(Float)
    carbs: Mapped[float | None] = mapped_column(Float)
    fat: Mapped[float | None] = mapped_column(Float)
    fiber: Mapped[float | None] = mapped_column(Float)
    salt: Mapped[float | None] = mapped_column(Float)
    origin_text: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)

    consumable: Mapped[Consumable] = relationship(
        primaryjoin="AdHocItem.id == foreign(Consumable.id)", uselist=False, viewonly=True
    )

    @property
    def name(self) -> str:
        return self.consumable.name


# ── Target bands ────────────────────────────────────────────────────────────


class TargetBand(Base):
    """One complete band profile per training type; frozen onto a day at approval."""

    __tablename__ = "target_band"
    __table_args__ = (
        UniqueConstraint("tenant_id", "valid_from", "training_type"),
        CheckConstraint(
            "training_type IN ('rest','strength','martial_arts') OR training_type IS NULL",
            name="ck_target_band_training_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    training_type: Mapped[str | None] = mapped_column(String(16))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)

    kcal_min: Mapped[float | None] = mapped_column(Float)
    kcal_opt_min: Mapped[float | None] = mapped_column(Float)
    kcal_opt_max: Mapped[float | None] = mapped_column(Float)
    kcal_target: Mapped[float | None] = mapped_column(Float)
    kcal_max: Mapped[float | None] = mapped_column(Float)

    protein_min: Mapped[float | None] = mapped_column(Float)
    protein_opt_min: Mapped[float | None] = mapped_column(Float)
    protein_opt_max: Mapped[float | None] = mapped_column(Float)
    protein_target: Mapped[float | None] = mapped_column(Float)
    protein_max: Mapped[float | None] = mapped_column(Float)
    protein_stretch: Mapped[float | None] = mapped_column(Float)

    carbs_min: Mapped[float | None] = mapped_column(Float)
    carbs_opt_min: Mapped[float | None] = mapped_column(Float)
    carbs_opt_max: Mapped[float | None] = mapped_column(Float)
    carbs_target: Mapped[float | None] = mapped_column(Float)
    carbs_max: Mapped[float | None] = mapped_column(Float)

    fat_min: Mapped[float | None] = mapped_column(Float)
    fat_opt_min: Mapped[float | None] = mapped_column(Float)
    fat_opt_max: Mapped[float | None] = mapped_column(Float)
    fat_target: Mapped[float | None] = mapped_column(Float)
    fat_max: Mapped[float | None] = mapped_column(Float)

    fiber_min: Mapped[float | None] = mapped_column(Float)
    fiber_opt_min: Mapped[float | None] = mapped_column(Float)
    fiber_opt_max: Mapped[float | None] = mapped_column(Float)
    fiber_target: Mapped[float | None] = mapped_column(Float)
    fiber_max: Mapped[float | None] = mapped_column(Float)
    fiber_stretch: Mapped[float | None] = mapped_column(Float)

    salt_min: Mapped[float | None] = mapped_column(Float)
    salt_opt_min: Mapped[float | None] = mapped_column(Float)
    salt_opt_max: Mapped[float | None] = mapped_column(Float)
    salt_target: Mapped[float | None] = mapped_column(Float)
    salt_max: Mapped[float | None] = mapped_column(Float)

    note: Mapped[str | None] = mapped_column(Text)


# ── Day log → meal → line item ──────────────────────────────────────────────


class DayLog(Base):
    __tablename__ = "day_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "date"),
        CheckConstraint("status IN ('draft','open','closed')", name="ck_day_log_status"),
        CheckConstraint(
            "created_by_kind IN ('user','agent','import')", name="ck_day_log_created_by_kind"
        ),
        CheckConstraint(
            "training_type IN ('rest','strength','martial_arts') OR training_type IS NULL",
            name="ck_day_log_training_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    weekday: Mapped[str | None] = mapped_column(String(16))
    reliable: Mapped[bool | None] = mapped_column(Boolean)  # NO default: NULL is an error
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    target_band_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("target_band.id")
    )  # frozen
    db_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capture_source: Mapped[str | None] = mapped_column(String(100))
    training_type: Mapped[str | None] = mapped_column(String(16))
    training_note: Mapped[str | None] = mapped_column(String(300))
    external_ref: Mapped[str | None] = mapped_column(String(300))
    generated_at: Mapped[datetime | None] = mapped_column(TS)
    generated_hash: Mapped[str | None] = mapped_column(String(64))
    created_by_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    agent_run_id: Mapped[str | None] = mapped_column(ID)
    approved_at: Mapped[datetime | None] = mapped_column(TS)
    approved_by: Mapped[str | None] = mapped_column(ID)
    # Cross-check against the source (frontmatter of an imported Markdown log)
    source_kcal: Mapped[float | None] = mapped_column(Float)
    source_protein: Mapped[float | None] = mapped_column(Float)
    source_carbs: Mapped[float | None] = mapped_column(Float)
    source_fat: Mapped[float | None] = mapped_column(Float)
    source_fiber: Mapped[float | None] = mapped_column(Float)
    source_salt: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TS, nullable=False, default=utcnow, onupdate=utcnow
    )

    meals: Mapped[list[Meal]] = relationship(
        back_populates="day_log", cascade="all, delete-orphan", order_by="Meal.position"
    )


class Meal(Base):
    __tablename__ = "meal"
    __table_args__ = (UniqueConstraint("day_log_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_log_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("day_log.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    time: Mapped[time | None] = mapped_column(Time)

    day_log: Mapped[DayLog] = relationship(back_populates="meals")
    line_items: Mapped[list[LineItem]] = relationship(
        back_populates="meal", cascade="all, delete-orphan", order_by="LineItem.position"
    )


class LineItem(Base):
    """No nutrient columns here — see ``views.line_item_macros``."""

    __tablename__ = "line_item"
    __table_args__ = (
        CheckConstraint("base_unit IN ('g','ml')", name="ck_line_item_base_unit"),
        CheckConstraint("origin IN ('manual','import','agent')", name="ck_line_item_origin"),
        CheckConstraint(
            "source_kind IN ('transcript','image','text') OR source_kind IS NULL",
            name="ck_line_item_source_kind",
        ),
        Index("ix_line_item_meal", "meal_id"),
        Index("ix_line_item_consumable", "consumable_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meal.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    consumable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("consumable.id", ondelete="RESTRICT"), nullable=False
    )
    portion_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("portion.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str | None] = mapped_column(String(32), ForeignKey("unit.code"))
    amount: Mapped[float | None] = mapped_column(Float)  # as captured
    base_amount: Mapped[float] = mapped_column(Float, nullable=False)  # FROZEN, in base_unit
    base_unit: Mapped[str] = mapped_column(String(2), nullable=False, default="g")
    amount_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_override: Mapped[str | None] = mapped_column(String(200))
    raw_text: Mapped[str | None] = mapped_column(Text)  # original text for audit / round trip
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    is_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    source_capture_id: Mapped[str | None] = mapped_column(ID)
    source_kind: Mapped[str | None] = mapped_column(String(16))
    alternatives: Mapped[list[Any] | None] = mapped_column(JSON)

    meal: Mapped[Meal] = relationship(back_populates="line_items")
    consumable: Mapped[Consumable] = relationship()


# ── Weight ──────────────────────────────────────────────────────────────────


class WeightEntry(Base):
    __tablename__ = "weight_entry"
    __table_args__ = (
        UniqueConstraint("tenant_id", "measured_at"),
        CheckConstraint("source IN ('scale_sync','manual','import')", name="ck_weight_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    measured_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    kg: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class BodyMeasurement(Base):
    """Tape-measure readings, one row per session (R76).

    The scale says how heavy, these say where it sits. Losing fat while keeping muscle
    shows up here as a shrinking waist next to unchanged limbs, which the weight alone
    cannot tell apart. Every circumference is optional: people measure what they measure.
    """

    __tablename__ = "body_measurement"
    __table_args__ = (
        UniqueConstraint("tenant_id", "measured_at"),
        CheckConstraint("source IN ('manual','import')", name="ck_body_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    measured_at: Mapped[datetime] = mapped_column(TS, nullable=False)
    #: All circumferences in centimetres.
    waist_cm: Mapped[float | None] = mapped_column(Float)
    belly_cm: Mapped[float | None] = mapped_column(Float)
    hip_cm: Mapped[float | None] = mapped_column(Float)
    chest_cm: Mapped[float | None] = mapped_column(Float)
    neck_cm: Mapped[float | None] = mapped_column(Float)
    thigh_cm: Mapped[float | None] = mapped_column(Float)
    arm_cm: Mapped[float | None] = mapped_column(Float)
    #: Optional body composition, if a scale or a caliper provided it.
    body_fat_pct: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


# ── Captures, attachments, transcripts ──────────────────────────────────────


class Attachment(Base):
    __tablename__ = "attachment"
    __table_args__ = (UniqueConstraint("tenant_id", "sha256"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class Capture(Base):
    __tablename__ = "capture"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash"),
        CheckConstraint("kind IN ('text','audio','image')", name="ck_capture_kind"),
        CheckConstraint(
            "status IN ('new','in_progress','assigned','processed','discarded','failed')",
            name="ck_capture_status",
        ),
        Index("ix_capture_tenant_status", "tenant_id", "status"),
        Index("ix_capture_tenant_date", "tenant_id", "target_date"),
        Index("ix_capture_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("user.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    target_date: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    attachment_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("attachment.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(TS)
    agent_run_id: Mapped[str | None] = mapped_column(ID)
    # A capture about one product (label photo, correction) instead of a day.
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="SET NULL")
    )

    attachment: Mapped[Attachment | None] = relationship()


class CaptureAttachment(Base):
    """Files that belong to one capture, in the order they were added.

    ``capture.attachment_id`` keeps pointing at the first one, so anything that
    only needs "the" file (transcription, thumbnails) stays unchanged.
    """

    __tablename__ = "capture_attachment"
    __table_args__ = (Index("ix_capture_attachment_capture", "capture_id", "position"),)

    capture_id: Mapped[str] = mapped_column(
        ID, ForeignKey("capture.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id: Mapped[str] = mapped_column(
        ID, ForeignKey("attachment.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Transcript(Base):
    __tablename__ = "transcript"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    capture_id: Mapped[str] = mapped_column(
        ID, ForeignKey("capture.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str | None] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[list[Any] | None] = mapped_column(JSON)
    duration_s: Mapped[float | None] = mapped_column(Float)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


# ── Agent runs, sessions, locks, day thread ─────────────────────────────────


class AgentRun(Base):
    __tablename__ = "agent_run"
    __table_args__ = (
        CheckConstraint("runner IN ('worker','external')", name="ck_agent_run_runner"),
        CheckConstraint(
            "mode IN ('historical','batch','manual','follow_up','assess')", name="ck_agent_run_mode"
        ),
        CheckConstraint(
            "status IN ('queued','running','finished','budget_exceeded','failed','cancelled')",
            name="ck_agent_run_status",
        ),
        Index("ix_agent_run_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    runner: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    captures: Mapped[list[Any] | None] = mapped_column(JSON)
    days: Mapped[list[Any] | None] = mapped_column(JSON)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    budget: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    summary_md: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class AgentSession(Base):
    """One isolated model conversation per day (ADR 0009)."""

    __tablename__ = "agent_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ID, ForeignKey("agent_run.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class AgentLock(Base):
    """Per-day lock shared by both runners (ADR 0005)."""

    __tablename__ = "agent_lock"

    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    runner: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str] = mapped_column(ID, nullable=False)
    locked_until: Mapped[datetime] = mapped_column(TS, nullable=False)


class DayMessage(Base):
    """The agent side of a day's thread (ADR 0010); captures are the user side."""

    __tablename__ = "day_message"
    __table_args__ = (
        CheckConstraint("role IN ('user','agent','system')", name="ck_day_message_role"),
        CheckConstraint(
            "kind IN ('text','summary','question','correction','note')", name="ck_day_message_kind"
        ),
        Index("ix_day_message_thread", "tenant_id", "date", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    capture_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("capture.id", ondelete="SET NULL")
    )
    run_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


class ProductProposal(Base):
    """A product change the agent read from a label photo or a note; a person decides.

    ``kind='update'`` carries changed values for an existing ``product_id``.
    ``kind='new'`` proposes a product that does not exist yet: the values live on the
    one-off consumable in ``consumable_id``, so a day can already log the food while
    the catalogue entry waits for a person (R54, R81).
    """

    __tablename__ = "product_proposal"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')", name="ck_product_proposal_status"
        ),
        CheckConstraint("kind IN ('update','new')", name="ck_product_proposal_kind"),
        Index("ix_product_proposal_tenant_status", "tenant_id", "status"),
        Index("ix_product_proposal_product", "product_id"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False)
    #: NULL for ``kind='new'`` — the product does not exist until a person approves.
    product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("product.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="update")
    #: The one-off consumable holding the proposed values while ``kind='new'`` is pending.
    consumable_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("consumable.id", ondelete="CASCADE")
    )
    capture_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("capture.id", ondelete="SET NULL")
    )
    run_id: Mapped[str | None] = mapped_column(ID)
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    decided_by: Mapped[str | None] = mapped_column(ID)


class ReportSnapshot(Base):
    """A rendered report frozen at a point in time, plus its written assessment."""

    __tablename__ = "report_snapshot"
    __table_args__ = (
        CheckConstraint(
            "status IN ('frozen','assessed','failed')", name="ck_report_snapshot_status"
        ),
        Index("ix_report_snapshot_tenant_created", "tenant_id", "created_at"),
        Index("ix_report_snapshot_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False)
    report_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str | None] = mapped_column(String(200))
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    today: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="frozen")
    #: the rendered report exactly as it was computed (reports/render/json.py)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assessment_md: Mapped[str | None] = mapped_column(Text)
    assessed_at: Mapped[datetime | None] = mapped_column(TS)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(16))


# ── Backup and audit ────────────────────────────────────────────────────────


class BackupJob(Base):
    __tablename__ = "backup_job"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    tenant_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("tenant.id"), index=True
    )  # NULL = all tenants
    started_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    path: Mapped[str | None] = mapped_column(String(500))
    size: Mapped[int | None] = mapped_column(Integer)
    manifest_hash: Mapped[str | None] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_target", "tenant_id", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ID, ForeignKey("tenant.id"), nullable=False, index=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ID)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TS, nullable=False, default=utcnow)


# Tables that carry a tenant_id column directly (used by the scoped repositories).
TENANT_SCOPED: tuple[type[Base], ...] = (
    User,
    Session,
    ApiToken,
    TenantSettings,
    Category,
    Consumable,
    Recipe,
    TargetBand,
    DayLog,
    WeightEntry,
    Attachment,
    Capture,
    AgentRun,
    AgentLock,
    DayMessage,
    AuditLog,
)
