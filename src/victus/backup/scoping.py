"""Which rows belong to a tenant — for tables with and without a ``tenant_id``.

Tables that carry ``tenant_id`` are filtered directly; child tables are filtered
through their parent (``portion`` → ``product`` → ``consumable`` → tenant).
``unit`` is global master data and is always exported in full.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Table, select

from victus.infrastructure.db.orm import Base

# child table → (foreign key column on the child, parent table, parent key column)
PARENT: dict[str, tuple[str, str, str]] = {
    "passkey_credential": ("user_id", "user", "id"),
    "product": ("id", "consumable", "id"),
    "recipe_batch": ("id", "consumable", "id"),
    "ad_hoc_item": ("id", "consumable", "id"),
    "portion": ("product_id", "product", "id"),
    "recipe_ingredient": ("recipe_id", "recipe", "id"),
    "meal": ("day_log_id", "day_log", "id"),
    "line_item": ("meal_id", "meal", "id"),
    "transcript": ("capture_id", "capture", "id"),
    "capture_attachment": ("capture_id", "capture", "id"),
    "agent_session": ("run_id", "agent_run", "id"),
}

GLOBAL_TABLES: frozenset[str] = frozenset({"unit"})


class UnscopedTableError(ValueError):
    """A table has neither ``tenant_id`` nor a known parent — refuse to guess."""


def export_tables() -> list[Table]:
    """All tables in foreign-key dependency order (parents first)."""
    return list(Base.metadata.sorted_tables)


def is_global(table: Table) -> bool:
    return table.name in GLOBAL_TABLES


def tenant_filter(table: Table, tenant_id: str) -> ColumnElement[bool]:
    """WHERE clause selecting the rows of ``table`` that belong to ``tenant_id``."""
    if table.name == "tenant":
        return table.c.id == tenant_id
    if "tenant_id" in table.c:
        return table.c.tenant_id == tenant_id
    if table.name in PARENT:
        fk, parent_name, pk = PARENT[table.name]
        parent = Base.metadata.tables[parent_name]
        return table.c[fk].in_(select(parent.c[pk]).where(tenant_filter(parent, tenant_id)))
    raise UnscopedTableError(f"table {table.name!r} cannot be scoped to a tenant")


def check_coverage() -> list[str]:
    """Names of tables that neither carry ``tenant_id`` nor have a parent mapping."""
    missing: list[str] = []
    for table in export_tables():
        if is_global(table) or table.name == "tenant" or "tenant_id" in table.c:
            continue
        if table.name not in PARENT:
            missing.append(table.name)
    return missing
