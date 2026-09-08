# ADR 0011 — No importer in the product; migration goes through the backup format

**Status:** accepted · **Date:** 2026-09-08

## Context

The first design included `victus import vault`, a CLI that parses the author's Markdown food diary and
loads it into Victus. That importer is inherently tied to one private vault layout (German headings,
table shapes, frontmatter keys) and runs exactly once. Keeping it in a public product means maintaining
parsers nobody else can use, shipping fixtures that mimic a private format, and growing a CLI surface for a
one-off event.

## Decision

- **Victus has no importer.** The product's only way to take in existing data is the backup format
  (ADR 0008): a ZIP with one JSONL file per table, blobs by hash and a manifest, restored with
  `victus backup restore`.
- Migrations from other systems are **external tools** that produce such an archive — either by writing
  JSONL directly or by using Victus as a library (ORM, unit of work, migrations) against a local SQLite
  database and then running `victus backup create`.
- The author's own one-off migration from a Markdown vault is such a tool and lives outside this
  repository. The generic pieces it needed — the quantity parser, the unit table and the product matcher —
  stay in `victus.domain.services` because the product itself uses them (product search, agent drafts).
- `docs/MIGRATION.md` documents the archive contract (table order, required columns, id rules) so that a
  third party can write their own migration.

## Consequences

- Smaller product surface: no `import` CLI group, no vault layout schema, no parser fixtures in the repo.
- The backup format doubles as the import format and therefore has to stay stable and documented.
- The review list (re-assigning `ad_hoc_item` line items to products) remains a product feature; it is
  useful after any migration and for agent drafts.
