# ADR 0002 — SQLite first, PostgreSQL ready

**Status:** accepted · **Date:** 2026-09-08

## Context

The target deployment is a home server serving one household. A predecessor schema already exists in SQLite and is
populated. Multi-tenancy, a web app, an hourly agent job and a backup daemon will write concurrently, and the owner
wants the option to move to PostgreSQL without a rewrite.

## Decision

- Start on **SQLite in WAL mode** with `PRAGMA foreign_keys = ON` enforced on every connection (event hook; a test
  asserts it).
- Use **SQLAlchemy 2.x** with dialect-neutral constructs only (no SQLite-specific types or raw SQL outside views), and
  **Alembic** for all schema changes from migration `0001`.
- Views are created via `op.execute` with one statement per dialect where needed.
- Full-text search uses FTS5 on SQLite and `pg_trgm` on PostgreSQL behind one `search.py` interface.
- CI runs the service, API and migration suites against **both** dialects.
- The backup format is JSONL per table (ADR 0008), so a dialect switch is `backup create` → change URL → `restore`.

## Consequences

- No database server to run for the common case; a single file to back up.
- Every feature that touches SQL is tested twice; PostgreSQL-only features (row-level security) are additive
  migrations guarded by dialect.
- Some SQLite-friendly shortcuts (e.g. `INSERT … ON CONFLICT` differences, `RETURNING`) need care; SQLAlchemy covers
  most of it.
- Row-level security exists only on PostgreSQL; on SQLite the repository scoping is the sole database-side defence.
