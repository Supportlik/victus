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
| GET | `/products?q=&category=&limit=&offset=` | Search, ranked by the name: exact, prefix, word prefix, substring, then fuzzy candidates. An empty `q` lists the catalogue A–Z, and `offset` pages through it  `on=<day>` returns the version of each product that applied on that day |
| POST | `/products` | Create product |
| GET / PATCH / DELETE | `/products/{id}` | Product detail |
| GET | `/products/{id}/versions` | Every version of the product, oldest first, with the days each one covers (R70) |
| POST | `/products/{id}/versions` | Record changed values from a day on `{valid_from, changes}`; the previous version is closed the day before and keeps its numbers |
| GET | `/products/{id}/usage?limit=` | The days this product was logged on, newest first, with amounts, kcal and draft flags, plus `item_count` over all of them rather than only the ones returned (R60). `{id}` may also be the one-off consumable a pending `new` proposal is logged against, which is how that proposal shows the day and meal it was eaten in |
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
| GET | `/days/{date}` | Day with meals, line items, computed macros, target band, findings, and `verdict` — the agent's short word on the day, its newest `summary` thread message. A finding's `message` is `{key, params}`, not a sentence: the client translates it (R78) |
| POST | `/days/{date}` | Create the day (`reliable` required, `training_type`, `notes`) |
| PUT | `/days/{date}` | Flags (`reliable`, `training_type`), notes; 404 if the day does not exist |
| POST | `/days/{date}/meals` | Add meal |
| PATCH | `/meals/{id}` | Rename a meal or change its time (`{name?, time?}`) |
| DELETE | `/meals/{id}` | Delete an **empty** meal; `409` while it still has line items (R53) |
| POST | `/meals/{id}/line-items` | Add line item |
| PATCH / DELETE | `/line-items/{id}` | Edit (`amount`, `unit_code`, `portion_id`, `consumable_id`, `estimated`, `amount_estimated`; a mark can be set back to `false`) / remove line item |
| POST | `/days/{date}/close` | `open → closed`, freeze `target_band_id` |
| POST | `/days/{date}/reopen` | Back to `open` |
| GET | `/days/{date}/messages` | The day's thread: captures and agent messages in order, with processing state |
| POST | `/days/{date}/messages` | Add a text message to the day (a capture with `target_date`); queues a `follow_up` run if the day already has a draft or is locked |

### Drafts

| Method | Path | Purpose |
|---|---|---|
| GET | `/drafts` | Days in `draft` or with draft line items, compact |
| GET | `/drafts/{date}/summary` | Summary as Markdown and JSON |
| POST | `/line-items/{id}/approve` | Accept **one** drafted item, optionally correcting `amount`, `unit_code` or `consumable_id`; the rest of the day stays a draft (R56) |
| POST | `/drafts/{date}/approve` | Body: corrections, `close` flag → `ApproveDay` |
| POST | `/drafts/{date}/discard` | Discard draft line items |

### Weight

| Method | Path | Purpose |
|---|---|---|
| GET | `/weight?from=&to=` | Weigh-ins |
| POST | `/weight` | Manual entry (`source` is forced to `manual`) |
| GET / POST | `/body-measurements?from=&to=&limit=` | Tape-measure sessions, oldest first; POST records one, every circumference optional and at least one required (R76) |
| DELETE | `/body-measurements/{id}` | Remove a session |
| DELETE | `/weight/{id}` | Only `manual` rows |
| POST | `/weight/import/scale` | Trigger scale cloud sync |
| POST | `/weight/import/csv` | Upload `timestamp;weight_kg` CSV |

### Settings

| Method | Path | Purpose |
|---|---|---|
| GET / POST | `/target-bands` | Target-band profiles |
| PATCH | `/target-bands/{id}` | Edit a profile (creates a new version if already used) |
| GET | `/settings/rules` | Your own instructions for the agent (R61), most important first |
| PUT | `/settings/rules` | Add a rule or replace the one with the same name; creates a settings version |
| DELETE | `/settings/rules/{name}` | Remove a rule |
| GET / PUT | `/settings` | Current tenant settings / new version |
| GET | `/settings/versions` | History |

### Captures

| Method | Path | Purpose |
|---|---|---|
| POST | `/captures` | Multipart: `text` and/or several `file` parts, which become **one** capture (R64) (audio, image), optional `target_date` or `product_id` (a capture about one product: label photo or spoken correction, R52; it never has a day). `201` with the capture; an upload whose content hash already exists returns `200` with the existing capture and `created: false` (no-op, R35). Audio is transcribed right away when a transcription provider is configured; a failed transcription leaves the capture `failed` and the upload still succeeds |
| GET | `/captures?status=&date=&product_id=&limit=` | List (newest first). Reading the list also purges captures that were discarded more than a day ago |
| DELETE | `/captures/{id}` | Delete a capture the agent has not used (`new`, `failed` or `discarded`); `409` otherwise. Its blob goes too when no other capture references it |
| GET / PATCH | `/captures/{id}` | Detail incl. `transcript`, `transcripts`, `attachment_id`, `attachment_mime` / change `status` (e.g. `discarded`), `target_date` or `product_id`. Re-targeting a `new` capture to a drafted or locked day queues a `follow_up` run |
| POST | `/captures/{id}/transcribe?force=` | (Re-)transcribe an audio capture: **every** recording in it, one transcript each. Parts that already have one are left alone unless `force`; `502` with problem details when the provider fails or none is configured |
| GET | `/attachments/{id}` | The attachment bytes (image, audio) inline, tenant-checked; `Cache-Control: private` |

### Events (server-sent)

One long-lived `GET` that says when this tenant's data changed, so an open page does not
have to poll for it (R83). The source is the `audit_log` table: every write in the
application books an entry, including writes from the worker container and from MCP, and
`MAX(id)` per tenant is the cursor. The server polls that cursor; the client is pushed to.

| Method | Path | Purpose |
|---|---|---|
| GET | `/events?cursor=` | `text/event-stream` for the authenticated tenant. Scopes `read` **and** `capture:read` (one of the counts counts captures). `503` when `events.enabled` is false — a clean refusal, so a client falls back to polling instead of hanging on a connection that will never speak |

**Request.** Session cookie or bearer token, as everywhere else; an unauthenticated
request is `401`. The response carries `Cache-Control: no-cache` and `X-Accel-Buffering: no`
(nginx buffers proxied responses by default, which would hold every event back).

**Events.** Every message carries `id:` = the cursor it reflects.

| Event | Payload | When |
|---|---|---|
| `hello` | `{"cursor": 41, "counts": {…}}` | Once, on connect. `cursor` is where this stream starts: the current one, or the resume point if one was given |
| `change` | `{"cursor": 43, "counts": {…}, "targets": [{"action": "day.update", "type": "day_log", "id": "12"}], "truncated": false}` | The cursor moved. `targets` are the audit entries since the previous message — the newest 50, oldest of them first; `truncated` is `true` when more happened than the list carries, and a client then reloads rather than patching |
| `heartbeat` | `{"cursor": 43}` | After `events.heartbeat_seconds` of silence, so proxies leave an idle connection alone |

**`targets` carry no `diff`.** Action, target type and target id only: a listener learns
that the day changed, never what was eaten.

**`counts`** are the four numbers the navigation badges show, computed server-side in one
place (`application/use_cases/events.py`), so the client needs no request of its own:

```json
{"new_captures": 2, "draft_days": 1, "open_days": 3, "pending_proposals": 0}
```

`open_days` counts days **before today** that are still `open` — today is expected to be
open while it is being lived. Which day is today follows the tenant's timezone (R69).

**Resuming.** A browser's `EventSource` sends the last `id:` back as `Last-Event-ID` when it
reconnects; `?cursor=` does the same for a client that is not an `EventSource` (the header
wins where both are present). The stream then greets at that cursor and sends one `change`
with what was missed, instead of replaying everything or losing it. An unreadable
`Last-Event-ID` is ignored rather than refused; that client simply starts from now.

### Report snapshots

A snapshot freezes a rendered report: the numbers of that period, stored with the date they were
computed. One assessment belongs to each snapshot (R57), so an assessment always refers to the
numbers it actually saw.

| Method | Path | Purpose |
|---|---|---|
| POST | `/reports/{name}/snapshots?from=&to=&label=` | Render and freeze; `201` with the snapshot |
| GET | `/reports/snapshots?report=&limit=` | Snapshots, newest first, without the frozen payload |
| GET | `/reports/snapshots/{id}` | One snapshot including its frozen `result` and its assessment |
| POST | `/reports/snapshots/{id}/assess` | Attach the assessment `{markdown}`; `409` when it already has one |
| DELETE | `/reports/snapshots/{id}` | Remove a snapshot |

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
| GET | `/agent/status` | Whether a queued run would be collected: `runner` is `ready`, `no_key` or `disabled`, with the model name only when ready. No key material is returned; the web app uses it to choose between **Process now** and the Claude hand-off (R67) |
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
| POST | `/reports/{name}/render?format=json|markdown&from=&to=&as_of=` | Render. `as_of` computes the whole report as of that day (R62); omitted means today |
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
| Pagination | `?limit=50&offset=100` on the list endpoints that have it; a short page is the last one. A cursor form stays reserved for collections that grow while they are read. |
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
