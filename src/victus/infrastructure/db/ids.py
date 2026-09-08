"""Opaque string identifiers for tenancy, auth and job tables.

Time-ordered UUIDv7 where the runtime offers it (Python ≥ 3.14), random UUIDv4
otherwise. Stored as 32 lowercase hex characters.
"""

from __future__ import annotations

import uuid


def new_id() -> str:
    maker = getattr(uuid, "uuid7", None)
    value = maker() if maker is not None else uuid.uuid4()
    return value.hex
