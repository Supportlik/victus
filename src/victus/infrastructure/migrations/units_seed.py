"""Unit master data for the ``unit`` table.

The single source of truth is ``victus.domain.services.units.UNITS`` (shared
with the quantity parser and the API); this module only flattens it into rows
for the migration seed so the database and the parser can never disagree.
"""

from __future__ import annotations

from victus.domain.services.units import UNITS as DOMAIN_UNITS

# code, singular, plural, unit_type, factor_base, needs_portion, fuzzy
UNITS: list[tuple[str, str, str, str, float | None, int, int]] = [
    (
        spec.code,
        spec.singular,
        spec.plural,
        spec.unit_type.value,
        spec.factor_base,
        int(spec.needs_portion),
        int(spec.fuzzy),
    )
    for spec in DOMAIN_UNITS.values()
]
