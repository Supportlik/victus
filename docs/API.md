# REST API

Base path `/api/v1`. The machine-readable contract is `/openapi.json` (OpenAPI 3.1); this page is the human overview.
Everything below is planned for Stage 1 unless marked otherwise.

## Authentication

| Mode | Used by | How | Scopes |
|---|---|---|---|
| **Session cookie** | Web app | Passkey login → `victus_session` cookie (HttpOnly, Secure, SameSite=Lax). Writes require header `X-CSRF-Token` (value from `GET /auth/me`). | full access of the user's role |
| **Bearer token** | Scripts, MCP over HTTP, external agents | `Authorization: Bearer vct_<8 chars>.<secret>`; created in the app or via `victus token create` | as granted at creation |

The tenant is always derived from the principal (session or token); it never appears in the URL.

### Scopes

| Scope | Grants |
|---|---|
| `read` | All GET endpoints except captures and attachments (agent runs and locks are readable) |
| `write` | Create/update/delete products, portions, recipes, batches, day logs, meals, line items, manual weight |
| `approve` | Approve or discard drafts, close/reopen days |
| `capture:read` / `capture:write` | Read captures and attachments / upload and change capture status |
| `agent:write` | Start and finish agent runs, create drafts |
| `settings` | Target bands, tenant settings, report definitions |
| `backup` | Trigger export/import, read backup jobs |
| `admin` | Tenant users, invitations, tokens of other users |

## Resources

### Auth

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/webauthn/register/options` | Challenge for registering a passkey (logged-in user or invitation) |
| POST | `/auth/webauthn/register/verify` | Store the credential |
| POST | `/auth/webauthn/login/options` | Challenge for login |
| POST | `/auth/webauthn/login/verify` | Verify assertion, create session |
| POST | `/auth/logout` | End session |
| GET | `/auth/me` | Current user, tenant, role, CSRF token |
| POST | `/auth/recovery` | Recovery code → short-lived session that may only add a passkey |
| GET / POST / DELETE | `/auth/passkeys[/{id}]` | Manage own passkeys |
| GET / POST / DELETE | `/auth/tokens[/{id}]` | Manage own API tokens (secret shown once) |

### Tenant

| Method | Path | Purpose |
|---|---|---|
| GET / PATCH | `/tenant` | Name, slug |
| GET / POST / DELETE | `/tenant/users[/{id}]` | Members and roles |
| POST | `/tenant/invites` | Invitation link for a new member |

### Master data

| Method | Path | Purpose |
|---|---|---|
| GET | `/units` | Global units |
| GET / POST / PATCH | `/categories[/{id}]` | Product categories |
| GET | `/products?q=&category=&limit=&cursor=` | Search (full-text + fuzzy score) |
| POST | `/products` | Create product |
| GET / PATCH / DELETE | `/products/{id}` | Product detail |
| GET / POST | `/products/{id}/portions` | Portions of a product |
| PATCH / DELETE | `/portions/{id}` | Edit portion |
| POST | `/products/match` | Free text → ranked candidates `{id, name, stage, score}` (same function the agent uses) |
| GET / POST | `/recipes` | Recipes |
| GET / PATCH / DELETE | `/recipes/{id}` | Recipe detail |
| PUT | `/recipes/{id}/ingredients` | Replace ingredient list |
| POST | `/recipes/{id}/batches` | Cook a batch (freezes nutrients) |
| GET / PATCH | `/batches/{id}` | Batch detail, mark used up |

### Day logs

| Method | Path | Purpose |
|---|---|---|
| GET | `/days?from=&to=&status=` | List days with computed macros |
| GET | `/days/{date}` | Day with meals, line items, computed macros, target band, findings |
| POST | `/days/{date}` | Create the day (`reliable` required, `training_type`, `notes`) |
| PUT | `/days/{date}` | Flags (`reliable`, `training_type`), notes; 404 if the day does not exist |
| POST | `/days/{date}/meals` | Add meal |
| PATCH | `/meals/{id}` | Rename a meal or change its time (`{name?, time?}`) |
| DELETE | `/meals/{id}` | Delete an **empty** meal; `409` while it still has line items (R53) |
| POST | `/meals/{id}/line-items` | Add line item |
| PATCH / DELETE | `/line-items/{id}` | Edit / remove line item |
| POST | `/days/{date}/close` | `open → closed`, freeze `target_band_id` |
| POST | `/days/{date}/reopen` | Back to `open` |
| GET | `/days/{date}/messages` | The day's thread: captures and agent messages in order, with processing state |
| POST | `/days/{date}/messages` | Add a text message to the day (a capture with `target_date`); queues a `follow_up` run if the day already has a draft or is locked |

### Drafts

| Method | Path | Purpose |
|---|---|---|
| GET | `/drafts` | Days in `draft` or with draft line items, compact |
| GET | `/drafts/{date}/summary` | Summary as Markdown and JSON |
| POST | `/drafts/{date}/approve` | Body: corrections, `close` flag → `ApproveDay` |
| POST | `/drafts/{date}/discard` | Discard draft line items |

### Weight

| Method | Path | Purpose |
|---|---|---|
| GET | `/weight?from=&to=` | Weigh-ins |
| POST | `/weight` | Manual entry (`source` is forced to `manual`) |
| DELETE | `/weight/{id}` | Only `manual` rows |
| POST | `/weight/import/scale` | Trigger scale cloud sync |
| POST | `/weight/import/csv` | Upload `timestamp;weight_kg` CSV |

### Settings

| Method | Path | Purpose |
|---|---|---|
| GET / POST | `/target-bands` | Target-band profiles |
| PATCH | `/target-bands/{id}` | Edit a profile (creates a new version if already used) |
| GET / PUT | `/settings` | Current tenant settings / new version |
| GET | `/settings/versions` | History |

### Captures

| Method | Path | Purpose |
|---|---|---|
| POST | `/captures` | Multipart: `text` and/or `file` (audio, image), optional `target_date` or `product_id` (a capture about one product: label photo or spoken correction, R52; it never has a day). `201` with the capture; an upload whose content hash already exists returns `200` with the existing capture and `created: false` (no-op, R35). Audio is transcribed right away when a transcription provider is configured; a failed transcription leaves the capture `failed` and the upload still succeeds |
| GET | `/captures?status=&date=&product_id=&limit=` | List (newest first). Reading the list also purges captures that were discarded more than a day ago |
| DELETE | `/captures/{id}` | Delete a capture the agent has not used (`new`, `failed` or `discarded`); `409` otherwise. Its blob goes too when no other capture references it |
| GET / PATCH | `/captures/{id}` | Detail incl. `transcript`, `attachment_id`, `attachment_mime` / change `status` (e.g. `discarded`), `target_date` or `product_id`. Re-targeting a `new` capture to a drafted or locked day queues a `follow_up` run |
| POST | `/captures/{id}/transcribe?force=` | (Re-)transcribe an audio capture; `502` with problem details when the provider fails or none is configured |
| GET | `/attachments/{id}` | The attachment bytes (image, audio) inline, tenant-checked; `Cache-Control: private` |

### Product proposals

The agent never changes a product on its own: what it reads from a label photo or a spoken
correction becomes a proposal a person approves (R54).

| Method | Path | Purpose |
|---|---|---|
| GET | `/proposals?status=pending&product_id=&limit=` | Pending proposals with `changes` and the product's `current` values |
| GET | `/proposals/{id}` | One proposal |
| POST | `/proposals/{id}/approve` | Apply it (optional body `{changes}` corrects a misread value), mark the product `verified`, set the capture `processed` |
| POST | `/proposals/{id}/reject` | Discard it and the capture; `409` when already decided |

### Agent

| Method | Path | Purpose |
|---|---|---|
| POST | `/agent/runs` | Queue a run on demand `{mode, captures[], from, to}` — the app's **Process now** button; `202 Accepted` with the run (`status: queued`); the worker picks it up within `agent.poll_seconds` (no cron needed) |
| GET | `/agent/runs?limit=&status=` | Runs with tokens, cost, summary |
| GET | `/agent/runs/{id}` | One run incl. `sessions[]` (one per drafted day) |
| POST | `/agent/runs/{id}/cancel` | Cancel a queued or running run; releases its locks |
| GET | `/agent/locks` | Current per-day locks (`date`, `runner`, `run_id`, `locked_until`) |
| DELETE | `/agent/locks/{date}` | Force-release a lock regardless of holder (operator escape hatch; scope `agent:write` or `admin`) |

### Reports (Stage 2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/reports` | Built-in and tenant definitions |
| POST / PUT / DELETE | `/reports/{name}` | Manage tenant definitions |
| POST | `/reports/{name}/render?format=json|markdown|svg&from=&to=` | Render |
| GET | `/reports/checkup` | Shortcut: built-in check-up, default window |

### Backup

| Method | Path | Purpose |
|---|---|---|
| POST | `/backup/export` | Start export job |
| GET | `/backup/jobs[/{id}]` | Job list / detail |
| GET | `/backup/jobs/{id}/download` | Download archive |
| POST | `/backup/import?dry_run=` | Upload archive; dry run reports counts only |
| GET / PUT | `/backup/schedule` | Cron and retention |

### System

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{status, db, storage, scheduler, backup_age_hours}` — no auth |
| GET | `/version` | Package version and git SHA |
| GET | `/openapi.json` | Contract |
| — | `/mcp` | Streamable HTTP MCP endpoint (bearer token; Stage 3) |

## Conventions

| Topic | Convention |
|---|---|
| Errors | `application/problem+json` (RFC 9457): `{type, title, status, detail, instance, errors[]}`. Validation errors list field paths. |
| Not found vs. forbidden | A resource of another tenant is **404**, never 403 (no existence leak). |
| Pagination | Cursor based: `?limit=50&cursor=<opaque>`; response carries `next_cursor`. |
| Dates | `date` as ISO `YYYY-MM-DD`; timestamps ISO 8601 with offset. |
| Numbers | Decimal point; grams with one decimal, kcal integer, salt two decimals. |
| Idempotency | `POST /captures` deduplicates by content hash; other POSTs accept `Idempotency-Key`. |
| Versioning | Path version `v1`; breaking changes get `v2`, additive changes do not. |

## Client generation

```bash
cd web
npm run api:generate   # @hey-api/openapi-ts against http://localhost:8090/openapi.json
```

CI regenerates the client and fails on a diff (`.github/workflows/web.yml`).
