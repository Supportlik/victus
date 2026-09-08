# Backup and restore — runbook

This page is written to be followed under stress. Commands are complete; paths assume the reference deployment
(`deploy/docker-compose.yml`, backups bind-mounted at `/backups` inside the containers). Backup create/verify ship in
Stage 1, the schedule in Stage 3.

## Format

One archive per run: `victus-<tenant|all>-<UTC timestamp>.zip`

```
victus-alice-20260915T030002Z.zip
├─ manifest.json
├─ data/
│  ├─ tenant.jsonl
│  ├─ user.jsonl
│  ├─ passkey_credential.jsonl
│  ├─ api_token.jsonl              # hashes only
│  ├─ tenant_settings.jsonl
│  ├─ target_band.jsonl
│  ├─ category.jsonl  unit.jsonl  consumable.jsonl  product.jsonl  portion.jsonl
│  ├─ recipe.jsonl  recipe_ingredient.jsonl  recipe_batch.jsonl  ad_hoc_item.jsonl
│  ├─ day_log.jsonl  meal.jsonl  line_item.jsonl
│  ├─ weight_entry.jsonl
│  ├─ capture.jsonl  attachment.jsonl  transcript.jsonl
│  ├─ agent_run.jsonl  audit_log.jsonl
├─ blobs/
│  └─ <sha256>                      # attachments, named by hash
└─ snapshot/victus.db               # optional SQLite VACUUM INTO copy
```

`manifest.json`:

| Field | Meaning |
|---|---|
| `victus_version`, `schema_revision` | Package version and Alembic head at export time |
| `created_at`, `tenant` | UTC timestamp; tenant slug or `all` |
| `tables[]` | `{name, rows, sha256}` per JSONL file |
| `blobs` | `{count, bytes}` |
| `snapshot` | `{present, sha256}` |
| `manifest_sha256` | Hash of the manifest without this field |

JSONL rows are plain dictionaries with ISO dates; IDs are preserved. Any text editor or `jq` can read them.

## Commands

| Task | CLI (inside the container) | Shell wrapper (host) |
|---|---|---|
| Create for all tenants | `victus backup create --all` | `deploy/backup/backup.sh` |
| Create for one tenant | `victus backup create --tenant alice` | `deploy/backup/backup.sh alice` |
| Verify an archive | `victus backup verify <zip>` | `deploy/backup/verify.sh <zip>` |
| Restore | `victus backup restore <zip> [--tenant <slug>] [--dry-run]` | `deploy/backup/restore.sh <zip>` |
| List | `victus backup list` | `ls -lt $BACKUP_DIR` |
| Schedule (daemon) | `victus backup schedule --daemon` (the `backup` service) | – |
| Apply retention now | `victus backup prune` | – |

Run inside Compose: `docker compose exec api victus backup …`. The wrappers do exactly that plus safety checks
(stop `worker` before restore, confirm prompts, log to `backup.log`).

`verify` restores into a temporary SQLite file, compares row counts and hashes with the manifest, runs the FK check,
and deletes the temporary file. Exit 0 = good.

## Restore — step by step (same server)

1. Identify the archive: `ls -lt $BACKUP_DIR | head`.
2. Verify it: `docker compose exec api victus backup verify /backups/<zip>` → must print `OK`.
3. Stop writers: `docker compose stop worker backup`.
4. Safety copy of the current state: `docker compose exec api victus backup create --all` (gives you a way back).
5. Dry run: `docker compose exec api victus backup restore /backups/<zip> --dry-run` → shows counts that will be written.
6. Restore: `docker compose exec api victus backup restore /backups/<zip>` (existing rows of that tenant are replaced; other tenants untouched).
7. Check: `docker compose exec api victus shell -c "select count(*) from day_log"` and compare with the manifest.
8. Start writers: `docker compose start worker backup`.
9. Open the app, look at yesterday's day and the check-up report.
10. Note the incident in `CHANGELOG.md` or your operations log.

## Restore one tenant into a new tenant (clone)

```bash
docker compose exec api victus backup restore /backups/<zip> --tenant alice --as alice-test
```

Useful for trying a migration or a data fix without touching production data.

## Restore a single day from JSONL

When one day was damaged and a full restore is overkill:

```bash
unzip -p $BACKUP_DIR/<zip> data/day_log.jsonl   | jq -c 'select(.date=="2026-08-19")' > day.jsonl
unzip -p $BACKUP_DIR/<zip> data/meal.jsonl      | jq -c 'select(.day_log_id=="<id from day.jsonl>")' > meals.jsonl
unzip -p $BACKUP_DIR/<zip> data/line_item.jsonl | jq -c --slurpfile m meals.jsonl 'select(.meal_id as $x | $m[].id | index($x))' > items.jsonl
docker compose exec -T api victus import jsonl --tenant alice --replace-day 2026-08-19 < <(cat day.jsonl meals.jsonl items.jsonl)
```

`import jsonl` validates against the current schema and refuses foreign-key gaps.

## Rebuild on a fresh server — 10 steps

1. Install Docker + Compose and your VPN client; join the network.
2. Restore DNS: `victus.example.com` → the new server's VPN address.
3. Copy `deploy/` (or clone the repository), restore `.env` from your password manager — **same `RP_ID`**.
4. Create the backup directory and copy the latest archive into it.
5. `docker compose pull && docker compose up -d api` (migrations run to head).
6. `docker compose exec api victus backup verify /backups/<zip>`.
7. `docker compose exec api victus backup restore /backups/<zip>`.
8. `docker compose up -d` (web, worker, backup).
9. Log in with an existing passkey (works because `RP_ID` is unchanged). If no device with a passkey survived, use the recovery code via the app's *Recovery* link.
10. `curl …/api/v1/health` → `backup_age_hours` resets after the first scheduled run; add the host to monitoring.

## Retention

Default 7 daily, 8 weekly, 12 monthly (`backup.retention.*`). `prune` never deletes the newest archive and never
deletes an archive that failed verification (kept and flagged in `backup_job`).

## Health indicator

`GET /api/v1/health` returns `backup_age_hours`. Above `backup.max_age_hours` (30) the field is flagged `"warn"`; the
Angular header shows a red dot. The worker also logs a warning hourly.

## Monthly check (5 minutes)

- [ ] `ls -lt $BACKUP_DIR | head -3` — newest is < 24 h old
- [ ] `verify` on the newest archive returns `OK`
- [ ] `df -h $BACKUP_DIR` — > 20 % free
- [ ] Open the newest `manifest.json`; row counts grow, not shrink
- [ ] Once a quarter: full restore into `--as <slug>-drill`, open the app, delete the drill tenant
