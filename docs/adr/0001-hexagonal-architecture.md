# ADR 0001 — Hexagonal architecture

**Status:** accepted · **Date:** 2026-09-08

## Context

Victus has four primary adapters that must all execute the same business operations with the same authorisation:
a REST API (web app, scripts), an MCP server (agents), a CLI (operations, import, backup) and an in-house agent worker.
The predecessor kept its logic in scripts that each re-implemented parsing and calculation; two scripts had their own
regex for the same number, and a format change silently lost data.

## Decision

Adopt ports-and-adapters:

- `domain/` — entities, value objects and services as pure functions; no I/O, no framework imports.
- `application/` — one use case per business action, ports as `typing.Protocol`, a `UnitOfWork` marking exactly one
  transaction per execution, a `TenantContext` required by every use case and repository call.
- `infrastructure/` — implementations of the ports (SQLAlchemy, WebAuthn, transcription, LLM, storage, locks).
- Primary adapters (`api/`, `mcp/`, `cli/`, `agent/`) call use cases only.

Dependencies point inward; an import-linter contract will enforce it in CI.

## Consequences

- Business rules exist once and are unit-testable without a database (fast test pyramid base).
- REST and MCP cannot drift: both are thin mappings onto the same use cases, so scopes and tenant checks are shared.
- More files and some ceremony (DTOs, ports, in-memory doubles) than a plain FastAPI + ORM app.
- Reports, importer and backup are additional adapters and must respect the same rule: no SQL outside infrastructure.
