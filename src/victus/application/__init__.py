"""Application layer: use cases, ports and the tenant context.

Every primary adapter (API, MCP, CLI, agent) talks to the system through a use
case in ``victus.application.use_cases``; a use case execution is exactly one
transaction (``UnitOfWork``) and always receives a ``TenantContext``.
"""
