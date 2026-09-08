"""Victus — self-hosted nutrition tracking.

The package is organised in hexagonal layers (see ``docs/ARCHITECTURE.md``):

* ``victus.domain`` — entities, value objects and pure domain services
* ``victus.application`` — use cases, ports and the tenant context
* ``victus.infrastructure`` — adapters (database, storage, providers)
* ``victus.api`` / ``victus.mcp`` / ``victus.cli`` / ``victus.agent`` — primary adapters
"""

__version__ = "0.1.0.dev0"
