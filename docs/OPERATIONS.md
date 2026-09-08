# Operations — incident runbook

Symptom → check → action. Commands assume `cd` into the stack directory with `docker-compose.yml` and `.env`.

## First minute

```bash
docker compose ps                                  # which service is down / restarting
docker compose logs --since 15m api worker | tail -200
curl -s http://127.0.0.1:8090/api/v1/health | jq   # db, storage, scheduler, backup_age_hours
df -h /var/lib/docker $BACKUP_DIR                  # disk
```

## Incidents

### API down or restarting

| Check | Action |
|---|---|
| `docker compose logs api` shows `alembic` error | Migration failed → see *Migration failed* below |
| `RP_ID mismatch` at start | See *RP_ID trap* below |
| `database is locked` repeatedly | A stuck writer: `docker compose restart worker`; if it persists, `victus shell -c "PRAGMA wal_checkpoint(TRUNCATE)"` |
| Port `8090` in use | Another service grabbed it → change `WEB_PORT` in `.env` |
| OOM kill (`docker inspect … | grep OOM`) | Raise memory limit in Compose; check image count per agent run |

### Worker stuck / agent runs never finish

| Check | Action |
|---|---|
| `GET /agent/runs` shows `status=running` for > 1 h | `docker compose exec api victus agent cancel <run_id>` → sets status `cancelled`, releases locks |
| `GET /agent/locks` shows expired `locked_until` | Locks expire on their own; force: `victus agent unlock --tenant alice --date 2026-09-07` |
| Anthropic/OpenAI 401/429 in logs | Key invalid or quota → rotate key in `.env`, `docker compose up -d worker`; runs resume next tick |
| Budget exceeded every run | Raise `agent.budget.*` or lower `max_images`; check for a capture with many photos |

### Lock held by another run

`draft_create` returns `LockHeldByOtherRun`. This is the two-runner protection working. Either wait for
`locked_until` (default 5 min) or `victus agent unlock` if you are sure the other run is dead.

### Migration failed / roll back

```bash
docker compose exec api alembic current
docker compose exec api alembic history | head
docker compose exec api alembic downgrade -1          # or a specific revision
sed -i 's/^VICTUS_IMAGE_TAG=.*/VICTUS_IMAGE_TAG=v0.3.1/' .env && docker compose up -d   # pin the previous image
```

Before any schema change: `victus backup create --all`. If the downgrade fails, restore that backup
([BACKUP.md](BACKUP.md)).

### Passkey lost

| Situation | Action |
|---|---|
| Another passkey exists | Log in with it → Settings → Passkeys → add new device |
| Recovery code available | App → *Recovery* → enter code → a 15-minute session that may only register a passkey |
| Neither | `docker compose exec api victus user reset-passkeys --tenant alice --email alice@example.com` → prints a one-time enrolment URL (valid 15 min). This is the admin path; it is logged in `audit_log`. |

### RP_ID trap

Symptom: passkeys stop working after a domain change, or the API refuses to start with `RP_ID mismatch: configured
"x", pinned "y"`.

- If you changed the domain **by accident**: set `VICTUS_AUTH__RP_ID` back to the pinned value.
- If the change is **intentional**: every passkey is void. `victus auth repin --rp-id <new> --yes`, then every user
  re-enrols via recovery code or admin URL.

### Revoke a token

```bash
docker compose exec api victus token list --tenant alice
docker compose exec api victus token revoke vct_xxxxxxxx
```

Or in the app: Settings → API tokens → revoke. Revocation is immediate (tokens are checked per request).

### Disk full

| Check | Action |
|---|---|
| Data disk | Blobs: `victus blobs gc` deletes attachments no capture references; WAL: `PRAGMA wal_checkpoint(TRUNCATE)` |
| Backup disk | `victus backup prune`; lower retention in config |
| Docker | `docker system prune -f` (images only) |

### Scale sync failing

Logs show `scale_sync: 401/403`. Vendor cloud APIs are unofficial; the client version string may need updating. Check
`infrastructure/weight/scale_sync.py` constants against the vendor's current app, update, redeploy. Weight can be
entered manually meanwhile (`POST /weight`, `source=manual`).

### Transcription errors

| Log | Action |
|---|---|
| `413` / file too large | Lower the recording length on the phone or set `transcription.ffmpeg_path` for conversion |
| `openai: 401` | Rotate `VICTUS_PROVIDERS__OPENAI_API_KEY` |
| Numbers transcribed wrongly (`1325` instead of `132.5`) | Extend `transcription.vocabulary_prompt` in tenant settings |

### High agent cost

`GET /agent/runs` sorted by `cost_usd`. Usual causes: many photos per capture, `batch` mode over weeks of backlog, a
prompt loop. Lower `agent.budget.max_usd`, switch to `historical`, and inspect the run's tool-call count.

## Reading logs

```bash
docker compose logs -f --tail 200 api            # JSON lines: ts, level, request_id, tenant, msg
docker compose logs worker | jq 'select(.run_id=="7f3a…")'
```

Set `VICTUS_SERVER__LOG_LEVEL=debug` temporarily for SQL and tool-call traces.

## Inspecting the database

```bash
docker compose exec api victus shell                       # sqlite3 / psql with the configured URL
docker compose exec api victus shell -c "select date, status, reliable from day_log order by date desc limit 7"
docker compose exec api victus shell -c "select * from source_check"     # cross-check view
```

Read-only by default; add `--write` for fixes and record what you did in `audit_log` via `victus audit note "…"`.

## Hotfix release

1. Branch from the tag in production: `git checkout -b hotfix/x.y.z+1 vX.Y.Z`.
2. Fix, add a test that fails before and passes after, update `CHANGELOG.md`.
3. `git tag vX.Y.Z+1 && git push --tags` → `release.yml` builds and pushes images.
4. On the server: `victus backup create --all`, `docker compose pull`, `docker compose up -d`.
5. Merge the hotfix branch back to `main`.

## Escalation checklist

- [ ] Backup verified before any destructive step
- [ ] Incident noted (date, symptom, fix) in `CHANGELOG.md` or your operations log
- [ ] If data changed by hand: `audit_log` entry written
- [ ] Runbook updated if the path was missing here
