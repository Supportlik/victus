# Migration into Victus

**Victus has no importer** ([ADR 0011](adr/0011-no-importer-migration-via-backup.md)). Existing data enters the
system in one of three ways:

| Way | When | Tooling |
|---|---|---|
| **Backup archive** | bulk migration of history (days, products, weights) | write JSONL following the contract below, or use Victus as a library against a local SQLite database and run `victus backup create`; then `victus backup verify` and `victus backup restore` on the server |
| **REST API** | incremental migration, scripts | `POST /products`, `POST /days/{date}/meals`, … (see [API.md](API.md)) |
| **MCP tools** | agent-assisted migration | `product_create`, `line_item_create`, `day_approve`, … (see [MCP.md](MCP.md)) |

The author's own one-off migration from a Markdown vault is an external tool built on the library route; it is not
part of this repository. The generic pieces it needed — the quantity parser, the unit table and the three-stage
product matcher — live in `victus.domain.services` because the product uses them too.

## The archive contract

An archive is a ZIP as described in [BACKUP.md](BACKUP.md): `manifest.json`, `data/<table>.jsonl` (one JSON object
per row, column names as in the database), `blobs/<sha256>` for attachments, optional SQLite snapshot. For a
migration you only need the tables you fill; `victus backup verify` reports what is missing or unknown before
`restore` writes anything.

### Table order

Restore inserts in dependency order; write the files in the same order so a partial archive stays consistent:

1. `tenant` → `user` → `passkey_credential`, `api_token`, `tenant_settings`, `target_band`
2. `unit` (global; normally omitted — the schema seeds it), `category`
3. `consumable` → `product` → `portion`; `recipe` → `recipe_ingredient` → `recipe_batch`; `ad_hoc_item`
4. `day_log` → `meal` → `line_item`
5. `weight_entry`
6. `capture`, `attachment`, `transcript`, `agent_run`, `agent_session`, `day_message`, `audit_log`

### Required columns per table (migration minimum)

| Table | Required | Notes |
|---|---|---|
| `tenant` | `id`, `slug`, `name` | one row; every other row references `tenant_id` |
| `consumable` | `id`, `tenant_id`, `kind` (`product` \| `recipe_batch` \| `ad_hoc`), `name` | supertype; the subtype row shares the `id` |
| `product` | `id`, `kind='product'`, `reference_amount` (100), `reference_unit` (`g` \| `ml`), nutrients per 100 (`kcal`, `protein`, `carbs`, `fat`, `fiber`, `salt` — `null` = not declared) | `verified`, `source`, `ean`, `external_ref` optional |
| `portion` | `id`, `product_id`, `unit_code`, `label`, `amount`, `amount_unit` | at most one `is_default` per product and unit |
| `recipe_batch` | `id`, `kind='recipe_batch'`, `recipe_id`, `total_weight_g`, `*_total` | nutrients per 100 g are derived from totals ÷ weight |
| `ad_hoc_item` | `id`, `kind='ad_hoc'`, `reference_amount`, `reference_unit`, nutrients | one-off items; the review list re-assigns them later |
| `day_log` | `id`, `tenant_id`, `date`, `reliable` (**no default** — `true`/`false`), `status` (`draft` \| `open` \| `closed`), `created_by_kind` (`import`) | `source_*` columns hold the source's declared totals for the round-trip check |
| `meal` | `id`, `day_log_id`, `position` | |
| `line_item` | `id`, `meal_id`, `position`, `consumable_id`, `base_amount`, `base_unit` (`g` \| `ml`), `origin` (`import`) | **no nutrient columns** — they are computed; `amount`/`unit_code` keep the captured quantity, `estimated` marks guesses |
| `weight_entry` | `id`, `tenant_id`, `measured_at` (ISO-8601, UTC), `kg`, `source` (`import`) | |
| `target_band` | `id`, `tenant_id`, `name`, `valid_from`, band columns | one complete profile per row (ADR 0007) |

Ids: string ids (`tenant`, `user`, captures, runs) are 32-hex UUIDs; integer ids are plain integers that must be
unique within the archive. Dates are `YYYY-MM-DD`, timestamps ISO-8601 with `Z`.

## Using Victus as a library

```python
from victus.application.tenant_context import TenantContext
from victus.infrastructure.db.engine import make_engine, make_session_factory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.migrations import runner

engine = make_engine("sqlite:///out/victus.db")
runner.upgrade(engine=engine)
factory = make_session_factory(engine)
with SqlAlchemyUnitOfWork(factory, TenantContext(tenant_id=tenant.id)) as uow:
    uow.products.add_product(
        "Skyr natural", kcal=63, protein=11, carbs=4, fat=0.2, fiber=0, salt=0.1
    )
    ...
    uow.commit()
```

Then `victus backup create --tenant <slug> --target out/` produces the archive.

## After the restore

- Check the review list in the app: `ad_hoc_item` line items are what the migration could not attach to a product.
  Re-assigning keeps the frozen quantity and lets nutrients propagate.
- Compare `day_log.source_kcal` with the computed day totals (`source_check` view) — the round-trip gate; days
  within 3 % can be marked `db_managed`.
- Days with `reliable = false` are estimated wholesale by the user and never count; days with `status = open`
  are not finished.
