# Backup and restore — runbook

This page is written to be followed under stress. Commands are complete; paths assume the reference deployment
(`deploy/docker-compose.yml`, backups bind-mounted at `/backups` inside the containers). Everything here ships
with Stage 1 (`src/victus/backup/`, `victus backup …`).

## Format

One archive per run: `victus-<tenant|all>-<UTC timestamp>.zip`

```
victus-alice-20260915T030002Z.zip
├─ manifest.json
├─ data/
│  ├─ tenant.jsonl  unit.jsonl
│  ├─ agent_lock.jsonl  agent_run.jsonl  attachment.jsonl  audit_log.jsonl  backup_job.jsonl
│  ├─ category.jsonl  consumable.jsonl  recipe.jsonl  target_band.jsonl  tenant_settings.jsonl
│  ├─ user.jsonl  weight_entry.jsonl
│  ├─ ad_hoc_item.jsonl  agent_session.jsonl  api_token.jsonl   # token hashes only
│  ├─ capture.jsonl  day_log.jsonl  passkey_credential.jsonl  product.jsonl  recipe_batch.jsonl  session.jsonl
│  ├─ day_message.jsonl  meal.jsonl  portion.jsonl  transcript.jsonl
│  └─ line_item.jsonl  recipe_ingredient.jsonl
├─ blobs/
│  └─ <sha256>                      # attachments, named by content hash
└─ snapshot/victus.db               # optional SQLite `VACUUM INTO` copy (file-based SQLite only)
```

`manifest.json` (`schemas/backup-manifest.schema.json`):

| Field | Meaning |
|---|---|
| `manifest_version` | `1` |
| `victus_version`, `schema_revision`, `database_dialect` | Package version, Alembic revision and dialect at export time |
| `created_at`, `tenant` | UTC timestamp; `{id, slug, name}` or `null` for an all-tenant archive |
| `tables[]` | `{name, rows, file, sha256}` per JSONL file — every table is present, even with 0 rows |
| `blobs[]` | `{sha256, size, mime, file}` per attachment |
| `includes_sqlite_snapshot`, `sqlite_snapshot` | `{file: "snapshot/victus.db", sha256, size}` when present |
| `sha256_total` | sha256 over the sorted list of all member hashes — quick integrity check |
| `notes` | Warnings from the export (e.g. an attachment missing on disk) |

JSONL rows are plain objects with the column names of the current schema: dates and timestamps are ISO 8601
(UTC), binary columns (`passkey_credential.public_key`, `credential_id`) are base64, JSON columns stay JSON.
IDs are preserved. Any text editor or `jq` can read them.

A tenant archive contains only that tenant's rows — for tables without a `tenant_id` (meals, line items,
portions, transcripts, …) the parent chain decides (`src/victus/backup/scoping.py`). `unit` is global master data
and always complete.

## Commands

| Task | CLI (inside the container) | Shell wrapper (host) |
|---|---|---|
| Create for all tenants | `victus backup create --all` | `deploy/backup/backup.sh` |
| Create for one tenant | `victus backup create --tenant alice` | `deploy/backup/backup.sh --tenant alice` |
| Skip the SQLite snapshot | `victus backup create --all --no-snapshot` | – |
| Verify an archive | `victus backup verify <zip>` · `--latest` | `deploy/backup/verify.sh <zip>` · `--latest` |
| Restore (same tenant, replace) | `victus backup restore <zip> --mode replace --yes` | `deploy/backup/restore.sh <zip>` |
| Restore into an empty database | `victus backup restore <zip>` (mode `fail_if_exists`) | – |
| Restore under a new slug | `victus backup restore <zip> --as alice-test` | `deploy/backup/restore.sh <zip> --as alice-test` |
| Dry run | `victus backup restore <zip> --dry-run` | `deploy/backup/restore.sh <zip> --dry-run` |
| List | `victus backup list` | `ls -lt $BACKUP_DIR` |
| Apply retention now | `victus backup prune [--dry-run]` | – |
| Schedule (daemon) | `victus backup schedule --daemon` (the `backup` service) | – |
| One scheduled cycle now | `victus backup schedule --once` | – |

Run inside Compose: `docker compose run --rm --no-deps backup backup …` (the image's entrypoint is `victus`).
The wrappers do exactly that plus safety checks (free space, stop `api`/`worker` before a restore, confirmation,
LF line endings). Directory and retention come from `backup.path` and `backup.retention.*` (`docs/CONFIGURATION.md`);
every command accepts `--target DIR` to override.

Exit codes: `0` ok · `1` verification or restore mismatch (database unchanged) · `2` input error.

### Restore modes

| `--mode` | Behaviour |
|---|---|
| `fail_if_exists` (default) | Refuses if any tenant of the archive (by id or slug) already exists |
| `replace` | Deletes the archived tenant's rows first (all-tenant archive: the whole database except `unit`), then inserts |
| `merge_new` | Inserts only rows whose primary key is free; existing rows are left alone; counts are not compared |

Every restore runs in **one transaction**: migrations to head first, rows inserted in foreign-key order, row counts
compared with the manifest, rollback on any mismatch. Attachments are written back to `storage.path` only after
the transaction committed. `--as <slug>` renames the (single) tenant of the archive; IDs are kept, so it works on
a database that does not already contain that tenant (a same-database clone would need ID remapping, which does
not exist yet — restore into a second instance instead).

`verify` checks the ZIP structure and every member hash, restores into a temporary SQLite file, compares the
counts, queries every view and runs `PRAGMA foreign_key_check`, then deletes the temporary file.

## Restore — step by step (same server)

1. Identify the archive: `ls -lt $BACKUP_DIR | head`.
2. Verify it: `deploy/backup/verify.sh <zip>` → must end with `archive OK`.
3. Safety copy of the current state: `deploy/backup/backup.sh --all` (gives you a way back).
4. Dry run: `deploy/backup/restore.sh <zip> --dry-run` → prints the row counts that would be written.
5. Restore: `deploy/backup/restore.sh <zip>` — the wrapper stops `api`, `worker` and `backup`, asks `yes`, runs
   `victus backup restore /backups/<zip> --mode replace --yes`, and starts the services again. A count mismatch
   rolls back and leaves the live data untouched.
6. Check: `docker compose exec api victus backup list` and compare the `day_log`/`line_item` counts printed by the
   restore with the manifest (`unzip -p <zip> manifest.json | jq '.tables[] | select(.name=="day_log")'`).
7. Open the app, look at yesterday's day and the check-up report.
8. Note the incident in your operations log.

## Restore one tenant into a new tenant (clone)

Use a second, empty instance (or a local checkout with an empty SQLite file):

```bash
VICTUS_DATABASE__URL=sqlite:///drill.db victus backup restore victus-alice-20260915T030002Z.zip --as alice-drill --yes
```

Useful for trying a data fix without touching production data.

## Restore a single day from JSONL

When one day was damaged and a full restore is overkill, pull the rows out of the big archive:

```bash
Z=$BACKUP_DIR/victus-alice-20260915T030002Z.zip
unzip -p $Z data/day_log.jsonl   | jq -c 'select(.date=="2026-08-19")' > day.jsonl
ID=$(jq -r .id day.jsonl)
unzip -p $Z data/meal.jsonl      | jq -c --argjson d "$ID" 'select(.day_log_id==$d)' > meal.jsonl
unzip -p $Z data/line_item.jsonl | jq -c --slurpfile m meal.jsonl 'select(.meal_id as $x | [$m[].id] | index($x))' > line_item.jsonl
```

Delete the damaged day in the app, wrap the three files plus the full `tenant.jsonl` and a manifest into a small
archive (see *Using the archive as an import format*) and restore it with `--mode merge_new`. For a single day it
is usually quicker to re-enter it in the app.

## Using the archive as an import format

Victus has no importer (ADR 0011): **the backup archive is the only way to bring existing data in**. A migration
tool from another system writes such an archive and runs `victus backup restore <zip> --mode merge_new`
(or `fail_if_exists` into an empty database). `docs/MIGRATION.md` points here.

**Minimal archive.** `manifest.json` (`manifest_version: 1`, `victus_version`, `schema_revision` = the Alembic head
of the target — `victus migrate current`, `created_at`, `tenant: null` or `{id, slug}`, one `tables[]` entry per
JSONL file with `rows` and `sha256`, `blobs: []`, `includes_sqlite_snapshot: false`, `sha256_total`) plus
`data/<table>.jsonl` for every table you fill. Tables you do not list are skipped with a warning; tables you list
must have correct counts. `unit` may be omitted — it is seeded by the migration; if included it is merged.

**Table order** (parents first; the restore inserts in this order, so foreign keys must already exist):

```
tenant, unit, agent_lock, agent_run, attachment, audit_log, backup_job, category, consumable, recipe,
target_band, tenant_settings, user, weight_entry, ad_hoc_item, agent_session, api_token, capture, day_log,
passkey_credential, product, recipe_batch, session, day_message, meal, portion, transcript, line_item,
recipe_ingredient
```

**ID rules.** String IDs (`tenant`, `user`, `session`, `api_token`, `attachment`, `capture`, `agent_run`,
`backup_job`) are 32 hex characters (`uuid7().hex`); any unique string works. Integer IDs (`consumable`,
`product`, `recipe_batch`, `ad_hoc_item`, `category`, `recipe`, `target_band`, `day_log`, `meal`, `line_item`,
`portion`, …) may be supplied or omitted per table — but foreign keys need them, so assign them yourself when a
child references the row. A `product`, `recipe_batch` or `ad_hoc_item` row must reuse the `id` of its
`consumable` row and carry the matching `kind`.

**Required columns** (everything else has a default or may be null):

| Table | Required |
|---|---|
| `tenant` | `slug`, `name` |
| `consumable` | `tenant_id`, `kind` (`product` \| `recipe_batch` \| `ad_hoc`), `name` |
| `product` / `ad_hoc_item` | `id` (= consumable id); nutrients per `reference_amount` (default 100) `reference_unit` (`g` \| `ml`); `null` = not declared |
| `recipe_batch` | `id`, `recipe_id`; frozen totals (`kcal_total`, …) and `total_weight_g` |
| `portion` | `product_id`, `unit_code`, `label`, `amount`, `amount_unit` |
| `target_band` | `tenant_id`, `name`, `valid_from`; band columns `<macro>_min/_opt_min/_opt_max/_target/_max` |
| `day_log` | `tenant_id`, `date`, `status` (`draft` \| `open` \| `closed`); set `reliable` explicitly — `null` is reported as an error |
| `meal` | `day_log_id`, `position` (unique per day) |
| `line_item` | `meal_id`, `position`, `consumable_id`, `base_amount` (frozen quantity in `base_unit`, default `g`) |
| `weight_entry` | `tenant_id`, `measured_at` (ISO UTC), `kg`, `source` (`scale_sync` \| `manual` \| `import`) |
| `unit` | `code`, `singular`, `plural`, `unit_type` (`mass` \| `volume` \| `count`) |

Nutrients are never written to `line_item`; the views compute them from the referenced consumable.
`unit_code` values must exist in `unit` (codes: `g, kg, ml, l, piece, slice, tbsp, tsp, cup, tub, …`; see
`victus.domain.services.units`). Verify your archive before importing: `victus backup verify my-export.zip`
performs the whole restore into a throw-away database and reports the first problem.

## Rebuild on a fresh server — 10 steps

1. Install Docker + Compose and your VPN client; join the network.
2. Restore DNS: `victus.example.com` → the new server's VPN address.
3. Copy `deploy/` (or clone the repository), restore `.env` from your password manager — **same `RP_ID`**.
4. Create the backup directory and copy the latest archive into it.
5. `docker compose pull && docker compose up -d api` (migrations run to head).
6. `deploy/backup/verify.sh <zip>`.
7. `deploy/backup/restore.sh <zip> --mode fail_if_exists --yes` (the database is empty).
8. `docker compose up -d` (web, worker, backup).
9. Log in with an existing passkey (works because `RP_ID` is unchanged). If no device with a passkey survived, use
   the recovery code via the app's *Recovery* link.
10. `curl …/api/v1/health` → `backup_age_hours` resets after the first scheduled run; add the host to monitoring.

## Retention

Default 7 daily, 8 weekly, 12 monthly (`backup.retention.*`), applied per scope (each tenant and `all`
separately) after every scheduled run or with `victus backup prune`. The newest archive is never deleted, nor is
an archive with a `<name>.zip.failed` marker — the scheduler writes that marker when verification failed and keeps
the archive for inspection.

## Scheduler

`victus backup schedule --daemon` runs `create --all` → `verify` → `prune` on `backup.cron` (five-field cron,
default `0 3 * * *`), records every run in `backup_job` (`status` `finished` | `verify_failed` | `failed`,
`verified`, `path`, `size`) and touches `<backup.path>/.victus-backup.alive` at least once a minute — the Compose
healthcheck of the `backup` service watches that file. `--once` runs one cycle and exits `1` if it failed.

## Health indicator

`GET /api/v1/health` returns `backup_age_hours` (age of the newest archive in `backup.path`). Above
`backup.max_age_hours` (30) the field is flagged `"warn"`; the Angular header shows a red dot. (Stage 1 API wiring.)

## Monthly check (5 minutes)

- [ ] `ls -lt $BACKUP_DIR | head -3` — newest is < 24 h old
- [ ] `deploy/backup/verify.sh --latest` ends with `archive OK`
- [ ] `df -h $BACKUP_DIR` — > 20 % free
- [ ] `unzip -p <newest> manifest.json | jq '.tables[] | select(.name=="day_log").rows'` grows, not shrinks
- [ ] Once a quarter: restore into a drill instance (`--as <slug>-drill`), open the app, delete the drill
