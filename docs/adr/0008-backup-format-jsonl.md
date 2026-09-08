# ADR 0008 — Backup format: JSONL per table + blobs + manifest

**Status:** accepted · **Date:** 2026-09-08

## Context

Backups must survive a database dialect switch (ADR 0002), be verifiable without trusting the tool that wrote them,
and be usable in an emergency by someone with standard command-line tools. A raw `sqlite3 .dump` or `pg_dump` is
dialect-bound and hard to inspect selectively; a bare file copy of `victus.db` is fast but says nothing about
consistency and cannot restore a single tenant.

## Decision

Each backup is a ZIP archive containing:

- `manifest.json` — Victus version, Alembic revision, timestamp, tenant scope, per-table row counts and SHA-256, blob
  count and size, and a hash of the manifest itself.
- `data/<table>.jsonl` — one JSON object per row, ISO dates, IDs preserved, dialect-neutral.
- `blobs/<sha256>` — attachments by content hash.
- `snapshot/victus.db` — optional `VACUUM INTO` copy on SQLite, for the fastest possible full restore of a single-tenant
  installation. It is an extra, never the primary format.

`victus backup verify` restores the archive into a temporary database, compares counts and hashes with the manifest
and runs the foreign-key check. `restore` supports whole installation, one tenant, or one tenant **as** a new slug.
Retention keeps 7 daily / 8 weekly / 12 monthly archives and never prunes an archive that failed verification.

## Consequences

- Restores work across SQLite and PostgreSQL and across Victus versions (JSONL is migrated forward on import).
- A single day can be reconstructed from three JSONL files with `jq` (documented in BACKUP.md).
- Archives are larger than a compressed SQL dump; acceptable for a household-scale dataset.
- Exporting through repositories (not raw SQL) means the backup respects tenant scoping and can be tested with the
  same fixtures as the application.
