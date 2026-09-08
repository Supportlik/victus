"""Shared integration fixtures: the database fixtures of ``tests/integration/db/conftest.py``
are re-exported here so every integration package (service, api, reports, backup) can use
``engine``, ``session_factory``, ``tenants``, ``uow_for`` and ``uow``."""

from __future__ import annotations

from tests.integration.db.conftest import (  # noqa: F401
    engine,
    session_factory,
    tenants,
    uow,
    uow_for,
)
