"""Database views — the one place where nutrients are calculated.

* ``consumable_per100``  every consumable normalised to "per 100 base units"
* ``line_item_macros``   nutrients of a line item = per100 × frozen base amount / 100
* ``day_macros``         totals per day (rounded like the predecessor: kcal 0, salt 2, rest 1)
* ``countable_days``     days that count for averages and TDEE (reliable and closed)
* ``source_check``       imported days whose computed kcal deviates > 3 % from the source

SQLite and PostgreSQL differ in two spots (``ROUND`` needs ``numeric`` in PG,
boolean literals), so the SQL is generated per dialect.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

VIEW_NAMES: tuple[str, ...] = (
    "source_check",
    "countable_days",
    "day_macros",
    "line_item_macros",
    "consumable_per100",
)


def _rnd(dialect: str, expr: str, digits: int) -> str:
    if dialect == "postgresql":
        return f"ROUND(CAST({expr} AS numeric), {digits})"
    return f"ROUND({expr}, {digits})"


def _true(dialect: str) -> str:
    return "TRUE" if dialect == "postgresql" else "1"


def view_statements(dialect: str) -> dict[str, str]:
    t = _true(dialect)
    return {
        "consumable_per100": """
CREATE VIEW consumable_per100 AS
  SELECT c.id, c.tenant_id, c.kind, c.name,
         p.kcal, p.protein, p.carbs, p.fat, p.fiber, p.salt, p.reference_unit AS base_unit
    FROM consumable c JOIN product p ON p.id = c.id
  UNION ALL
  SELECT c.id, c.tenant_id, c.kind, c.name,
         b.kcal_total    * 100.0 / NULLIF(b.total_weight_g, 0),
         b.protein_total * 100.0 / NULLIF(b.total_weight_g, 0),
         b.carbs_total   * 100.0 / NULLIF(b.total_weight_g, 0),
         b.fat_total     * 100.0 / NULLIF(b.total_weight_g, 0),
         b.fiber_total   * 100.0 / NULLIF(b.total_weight_g, 0),
         b.salt_total    * 100.0 / NULLIF(b.total_weight_g, 0),
         'g'
    FROM consumable c JOIN recipe_batch b ON b.id = c.id
  UNION ALL
  SELECT c.id, c.tenant_id, c.kind, c.name,
         a.kcal, a.protein, a.carbs, a.fat, a.fiber, a.salt, a.reference_unit
    FROM consumable c JOIN ad_hoc_item a ON a.id = c.id
""",
        "line_item_macros": """
CREATE VIEW line_item_macros AS
  SELECT li.id, li.meal_id, m.day_log_id, li.position,
         z.name, z.kind, z.tenant_id,
         li.base_amount, li.base_unit, li.amount, li.unit_code,
         li.estimated, li.amount_estimated, li.is_draft, li.display_override,
         z.kcal    * li.base_amount / 100.0 AS kcal,
         z.protein * li.base_amount / 100.0 AS protein,
         z.carbs   * li.base_amount / 100.0 AS carbs,
         z.fat     * li.base_amount / 100.0 AS fat,
         z.fiber   * li.base_amount / 100.0 AS fiber,
         z.salt    * li.base_amount / 100.0 AS salt
    FROM line_item li
    JOIN meal m ON m.id = li.meal_id
    JOIN consumable_per100 z ON z.id = li.consumable_id
""",
        "day_macros": f"""
CREATE VIEW day_macros AS
  SELECT d.id AS day_log_id, d.tenant_id, d.date, d.reliable, d.status,
         d.training_type, d.target_band_id,
         {_rnd(dialect, "SUM(lm.kcal)", 0)}    AS kcal,
         {_rnd(dialect, "SUM(lm.protein)", 1)} AS protein,
         {_rnd(dialect, "SUM(lm.carbs)", 1)}   AS carbs,
         {_rnd(dialect, "SUM(lm.fat)", 1)}     AS fat,
         {_rnd(dialect, "SUM(lm.fiber)", 1)}   AS fiber,
         {_rnd(dialect, "SUM(lm.salt)", 2)}    AS salt,
         COUNT(lm.id) AS item_count,
         SUM(CASE WHEN lm.is_draft = {t} THEN 1 ELSE 0 END) AS draft_items
    FROM day_log d
    LEFT JOIN meal m ON m.day_log_id = d.id
    LEFT JOIN line_item_macros lm ON lm.meal_id = m.id
   GROUP BY d.id, d.tenant_id, d.date, d.reliable, d.status, d.training_type, d.target_band_id
""",
        "countable_days": f"""
CREATE VIEW countable_days AS
  SELECT * FROM day_macros WHERE reliable = {t} AND status = 'closed'
""",
        "source_check": """
CREATE VIEW source_check AS
  SELECT d.id AS day_log_id, d.tenant_id, d.date, d.source_kcal, dm.kcal AS computed_kcal,
         dm.kcal - d.source_kcal AS deviation
    FROM day_log d JOIN day_macros dm ON dm.day_log_id = d.id
   WHERE d.source_kcal IS NOT NULL AND dm.kcal IS NOT NULL
     AND ABS(dm.kcal - d.source_kcal) > 0.03 * d.source_kcal
""",
    }


def drop_views(conn: Connection) -> None:
    for name in VIEW_NAMES:
        conn.execute(text(f"DROP VIEW IF EXISTS {name}"))


def create_views(conn: Connection, dialect: str | None = None) -> None:
    """Create all views (drops existing ones first). Order matters: dependencies first."""
    dialect = dialect or conn.dialect.name
    drop_views(conn)
    stmts = view_statements(dialect)
    for name in (
        "consumable_per100",
        "line_item_macros",
        "day_macros",
        "countable_days",
        "source_check",
    ):
        conn.execute(text(stmts[name]))
