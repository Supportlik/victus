# REST API

Base path `/api/v1`. The machine-readable contract is `/openapi.json` (OpenAPI 3.1); this page is the human overview.
Everything below is planned for Stage 1 unless marked otherwise.

## Authentication

| Mode | Used by | How | Scopes |
|---|---|---|---|
| **Session cookie** | Web app | Passkey login → `victus_session` cookie (HttpOnly, Secure, SameSite=Lax). Writes require header `X-CSRF-Token` (value from `GET /auth/me`). | the scopes of the user's role: an `owner` holds every scope, a `member` every scope except `admin` |
| **Bearer token** | Scripts, MCP over HTTP, external agents | `Authorization: Bearer vct_<8 chars>.<secret>`; created in the app or via `victus token create` | as granted at creation, and never more than its user's role holds |

The tenant is always derived from the principal (session or token); it never appears in the URL.

### Scopes

| Scope | Grants |
|---|---|
| `read` | All GET endpoints except captures and attachments (agent runs and locks are readable), report rendering and product matching |
| `write` | Day logs, meals, line items (as **drafts** without `approve`), day messages, manual weight and body measurements, recipes and batches, categories, settings, rules and target bands, storing and deleting report snapshots; product, version and portion writes, which without `approve` are **filed as proposals** |
| `approve` | Together with `write`: decide — approve or discard drafts, approve a proposal, close/reopen a day, set `reliable`, change or remove an approved line item, write the catalogue directly |
| `capture:read` / `capture:write` | Read captures and attachments / upload, re-target, transcribe and delete captures |
| `agent:write` | Start and finish agent runs, create drafts, withdraw a draft item, file product proposals and report assessments |
| `admin` | Tenant and its users, creating users, every token of the tenant (passes every other check too) |

There are no other scopes: `victus token create` and `POST /auth/tokens` refuse an unknown one.
Every route's full requirement is declared in one table (`api/scopes.py`) and checked before the
route runs; the use case checks the same scopes again. [SCOPES.md](SCOPES.md) is the generated
matrix of every route and MCP tool against the profiles below. A refusal is `403` with
`detail: "scope '…' required"`.

### Who manages tokens and users

| Action | Session of an `owner` | Session of a `member` | Token with `admin` | Any other token |
|---|---|---|---|---|
| `GET /auth/tokens`, `DELETE /auth/tokens/{id}` | every token of the tenant | own tokens only (another user's is `404`) | every token of the tenant | `403` |
| `POST /auth/tokens` | any scope | any scope but `admin` — nobody grants a scope they do not hold | scopes it holds | `403` |
| `GET /tenant`, `GET /tenant/users`, `POST /tenant/users` | yes | `403` | yes | `403` |

A token's scopes are capped by its user's role each time it is used, so a member's token never
carries `admin`, whenever it was created.

### Scope profiles

The table above says what each scope grants on its own. A profile is the other way round: what a
client should be able to do, and which boxes to tick for it. The settings page offers these as
presets next to the scope checkboxes, and [SCOPES.md](SCOPES.md) lists every tool and route for
each. A profile is checked by the tests exactly as written here: each is minted as a token and
every name under *Can*, *Becomes a proposal or a draft* and *Refused* is called against the
server's declarations.

"Without `approve`, nothing is a fact" (ADR 0013, SPEC R81) is what separates the profiles: a
client without `approve` may draft and propose as much as it likes, and every result waits for a
person.

#### Read-only

Scopes: `read` — reports, days, catalogue; nothing written.

```bash
victus token create --tenant alice --name "reports" --scopes read --days 90
```

- **Can:** `day_get`, `days_list`, `drafts_list`, `draft_summary`, `product_search`, `product_get`, `product_versions`, `product_usage`, `recipe_get`, `report_render`, `report_snapshots_list`, `report_snapshot_get`, `rules_list`, `body_measurements`, `GET /days/{day}`, `GET /products`, `POST /reports/{name}/render`, `GET /reports/checkup`, `GET /proposals`
- **Becomes a proposal or a draft:** nothing
- **Refused:** `day_thread_get` (it carries captures), `captures_open`, `capture_get`, `line_item_create`, `draft_create`, `product_propose`, `report_snapshot_create`, `weight_add`, `day_approve`, `GET /captures`, `GET /events`, `POST /products`, `POST /reports/{name}/snapshots`

#### Assistant that proposes

Scopes: `read,write,capture:read,capture:write,agent:write` — reads everything, including
captures, drafts days and files catalogue proposals, refines its own drafts, and creates no fact:
nothing approved, no day closed, no product written directly. This is the token to give Claude as
a connector, or Claude Code over HTTP.

```bash
victus token create --tenant alice --name "claude" --scopes read,write,capture:read,capture:write,agent:write --days 90
```

- **Can:** `day_thread_get`, `captures_open`, `capture_get`, `capture_mark`, `agent_run_start`, `draft_create`, `agent_message_add`, `agent_run_finish`, `line_item_update`, `line_item_delete`, `product_propose`, `report_snapshot_create`, `report_assess`, `day_message_add`, `rule_upsert`, `weight_add`, `body_add`, `GET /captures`, `GET /events`, `POST /reports/{name}/snapshots`
- **Becomes a proposal or a draft:** `line_item_create`, `product_create`, `product_update`, `product_version_create`, `portion_create`, `portion_update`, `portion_delete`, `POST /meals/{meal_id}/line-items`, `POST /products`, `PATCH /products/{product_id}`, `POST /products/{product_id}/versions`, `POST /products/{product_id}/portions`, `PATCH /portions/{portion_id}`, `DELETE /portions/{portion_id}`
- **Refused:** `day_approve`, `line_item_approve`, `draft_discard`, `POST /days/{day}/close`, `POST /days/{day}/reopen`, `POST /drafts/{day}/approve`, `POST /proposals/{proposal_id}/approve`, `POST /proposals/{proposal_id}/reject`, `DELETE /products/{product_id}`, `GET /tenant`

What "work on suggestions" covers, precisely:

- **Its drafts.** `line_item_update` changes a draft item's amount, unit, portion or product;
  `line_item_delete` withdraws a draft item; `draft_create` again replaces the day's draft. These
  apply to every **draft** item of the tenant, whoever drafted it — a draft is nobody's fact yet,
  and a person's own entries are never drafts, because a person's session holds `approve`. An
  **approved** item is refused (`scope 'approve' required`), as is setting `reliable` and closing
  or reopening a day.
- **Its proposals.** Every catalogue write is filed as a pending proposal (`202` over REST, the
  proposal as the tool result over MCP); `product_create` also returns
  `log_against_consumable_id`, so the day can log the new food before a person approves it.
  Deciding a proposal is refused. `proposal_update` (or `PATCH /proposals/{id}`) corrects a
  pending proposal this token filed, as long as no person has corrected it yet; it never applies
  one, and a proposal another token or a person touched answers `409` or `403` (R84).
- **The deliberate exceptions** of ADR 0013 are written directly, because they are a person's
  dictated numbers or instructions rather than inferences: `weight_add`, `body_add`,
  `rule_upsert`/`rule_delete`, `day_message_add`, and over REST recipes, categories, settings and
  target bands. A client that must not touch these needs a narrower token than this profile.

#### Capture uploader

Scopes: `capture:write` — a phone shortcut that uploads photos and recordings and nothing else.

```bash
victus token create --tenant alice --name "phone shortcut" --scopes capture:write --days 365
```

- **Can:** `POST /captures`, `PATCH /captures/{capture_id}`, `capture_mark`
- **Becomes a proposal or a draft:** nothing
- **Refused:** `GET /captures`, `GET /captures/{capture_id}`, `GET /attachments/{attachment_id}`, `captures_open`, `capture_get`, `GET /days/{day}`, `GET /auth/tokens`, `DELETE /auth/tokens/{token_id}`

It cannot read back what it uploaded, so a leaked shortcut token discloses nothing. The upload
answers with the new capture all the same, its status included when transcription failed.

#### In-house worker

Scopes: `read,write,capture:read,capture:write,agent:write` — what `victus worker` runs with. The
worker holds no token: it builds its context in-process with the assistant's scopes
(`agent/runner.py::WORKER_SCOPES`), and hands the model only `WORKER_TOOLS`, a smaller set. It
needs `read` and `capture:read` for the day thread, `agent:write` to draft and propose,
`capture:write` to mark captures processed and transcribe audio, and `write` to freeze report
snapshots and record the weigh-ins and measurements a capture dictates. It never holds `approve`.

```bash
victus worker --tenant alice
```

- **Can:** `day_thread_get`, `captures_open`, `capture_get`, `capture_mark`, `draft_create`, `agent_message_add`, `product_search`, `product_propose`, `report_render`, `report_snapshot_create`, `report_assess`, `weight_add`, `body_add`
- **Becomes a proposal or a draft:** `product_create`, `portion_create`, `portion_update`, `portion_delete`
- **Refused:** `day_approve`, `line_item_approve`, `draft_discard`, `line_item_create`, `line_item_delete`, `product_update`, `product_version_create`, `agent_run_start`

`agent_run_start` and `agent_run_finish` are refused only in the sense that the worker does not
hand them to the model: it starts and finishes the run itself.

#### Full delegate

Scopes: `read,write,approve,capture:read,capture:write,agent:write` — can also decide. **Whatever
this client writes is a fact**: items are approved as they are logged, catalogue writes are
applied, days can be approved and closed. Give it only to a client you trust exactly as much as
yourself; `admin` stays out of every profile.

```bash
victus token create --tenant alice --name "delegate" --scopes read,write,approve,capture:read,capture:write,agent:write --days 30
```

- **Can:** `day_approve`, `line_item_approve`, `draft_discard`, `line_item_create`, `product_create`, `product_update`, `portion_delete`, `POST /days/{day}/close`, `POST /proposals/{proposal_id}/approve`, `DELETE /products/{product_id}`
- **Becomes a proposal or a draft:** nothing
- **Refused:** `GET /tenant`, `GET /tenant/users`, `POST /tenant/users`

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
| GET / POST / DELETE | `/auth/tokens[/{id}]` | Own API tokens (secret shown once); an owner or `admin` sees and revokes every token of the tenant — see *Who manages tokens and users* |

### Tenant

| Method | Path | Purpose |
|---|---|---|
| GET | `/tenant` | Name, slug — owner or `admin` |
| GET / POST | `/tenant/users` | Members and roles / create a user and return its one-time recovery code — owner or `admin` |

Changing the tenant, removing users and invitation links are not implemented yet.

### Master data

| Method | Path | Purpose |
|---|---|---|
| GET | `/units` | Global units |
| GET / POST | `/categories` | Product categories |
| GET | `/products?q=&category=&limit=&offset=` | Search, ranked by the name: exact, prefix, word prefix, substring, then fuzzy candidates. An empty `q` lists the catalogue A–Z, and `offset` pages through it  `on=<day>` returns the version of each product that applied on that day |
| POST | `/products` | Create a product: `201` with `write` + `approve`; without `approve` a `new` proposal is filed instead and the answer is `202` with the proposal (ADR 0013) |
| GET / PATCH / DELETE | `/products/{id}` | Product detail / correct it (`200`, or `202` with a proposal without `approve`) / delete it (`write` + `approve`) |
| GET | `/products/{id}/versions` | Every version of the product, oldest first, with the days each one covers (R70) |
| POST | `/products/{id}/versions` | Record changed values from a day on `{valid_from, changes}`; the previous version is closed the day before and keeps its numbers. Without `approve`: a `version` proposal, `202` |
| GET | `/products/{id}/usage?limit=` | The days this product was logged on, newest first, with amounts, kcal and draft flags, plus `item_count` over all of them rather than only the ones returned (R60). `{id}` may also be the one-off consumable a pending `new` proposal is logged against, which is how that proposal shows the day and meal it was eaten in |
| GET / POST | `/products/{id}/portions` | Portions of a product / add one (`201`, or `202` with a proposal without `approve`) |
| PATCH / DELETE | `/portions/{id}` | Edit / remove a portion (`200`/`204`, or `202` with a proposal without `approve`) |
| POST | `/products/match` | Free text → ranked candidates `{id, name, stage, score}` (same function the agent uses) |
| GET / POST | `/recipes` | Recipes |
| GET / PATCH | `/recipes/{id}` | Recipe detail |
| PUT | `/recipes/{id}/ingredients` | Replace ingredient list |
| POST | `/recipes/{id}/batches` | Cook a batch (freezes nutrients) |
| GET | `/batches/{id}` | Batch detail |

### Day logs

| Method | Path | Purpose |
|---|---|---|
| GET | `/days?from=&to=&status=` | List days with computed macros |
| GET | `/days/{date}` | Day with meals, line items, computed macros, target band, findings, and `verdict` — the agent's short word on the day, its newest `summary` thread message. A finding's `message` is `{key, params}`, not a sentence: the client translates it (R78) |
| POST | `/days/{date}` | Create the day (`reliable` required, `training_type`, `notes`) |
| PUT | `/days/{date}` | Flags (`reliable`, `training_type`), notes; 404 if the day does not exist. Setting `reliable` needs `approve` |
| POST | `/days/{date}/meals` | Add meal |
| PATCH | `/meals/{id}` | Rename a meal or change its time (`{name?, time?}`) |
| DELETE | `/meals/{id}` | Delete an **empty** meal; `409` while it still has line items (R53) |
| POST | `/meals/{id}/line-items` | Add line item; without `approve` it arrives as a draft |
| PATCH / DELETE | `/line-items/{id}` | Edit (`amount`, `unit_code`, `portion_id`, `consumable_id`, `estimated`, `amount_estimated`; a mark can be set back to `false`; `meal_id` moves the item to another meal of the **same** day — `422` with `errors[].field = meal_id` for another day's meal, `404` for none) / remove line item. A draft needs `write`, an approved item `approve`; a draft item is withdrawn with `write` + `agent:write`. A person's change to the agent's draft is said in the day thread (R84) |
| POST | `/days/{date}/close` | `open → closed`, freeze `target_band_id` (`write` + `approve`) |
| POST | `/days/{date}/reopen` | Back to `open` (`write` + `approve`) |
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

Every route of this table but the two reads is a decision and needs `write` + `approve`.

### Weight

| Method | Path | Purpose |
|---|---|---|
| GET | `/weight?from=&to=` | Weigh-ins |
| POST | `/weight` | Manual entry (`source` is forced to `manual`) |
| GET / POST | `/body-measurements?from=&to=&limit=` | Tape-measure sessions, oldest first; POST records one, every circumference optional and at least one required (R76) |
| DELETE | `/body-measurements/{id}` | Remove a session |
| DELETE | `/weight/{id}` | Only `manual` rows |

### Settings

| Method | Path | Purpose |
|---|---|---|
| GET / POST | `/target-bands` | Target-band profiles |
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
| POST | `/reports/{name}/snapshots?from=&to=&label=` | Render and freeze; `201` with the snapshot. Storing one is a write: `read` + `write` |
| GET | `/reports/snapshots?report=&limit=` | Snapshots, newest first, without the frozen payload |
| GET | `/reports/snapshots/{id}` | One snapshot including its frozen `result` and its assessment |
| POST | `/reports/snapshots/{id}/assess` | Attach the assessment `{markdown}`; `409` when it already has one. `agent:write` or `write` |
| DELETE | `/reports/snapshots/{id}` | Remove a snapshot |

### Product proposals

The agent never changes a product on its own: what it reads from a label photo or a spoken
correction becomes a proposal a person approves, corrects or rejects (R54, R84).

| Method | Path | Purpose |
|---|---|---|
| GET | `/proposals?status=pending&product_id=&consumable_id=&limit=` | Pending proposals with `changes` and the product's `current` values. `consumable_id` finds the `new` proposal a one-off consumable belongs to. `proposed` holds the values as filed once a person changed one, `null` otherwise |
| GET | `/proposals/{id}` | One proposal |
| PATCH | `/proposals/{id}` | Amend a pending proposal without deciding it: `{changes, rationale?}`, merged into what it carries, `null` withdraws a field. Validated like the decision (`422`); `409` once decided; `404` when missing. Scope `approve` for any pending proposal, `agent:write` only for one the same token filed and no person has corrected. Audited as `product.proposal.amend`; the first change by a person keeps the filed values in `proposed` (R84) |
| POST | `/proposals/{id}/approve` | Apply it (optional body `{changes, fields}`: `changes` corrects a value — the web app sends what a person typed — and `fields` applies only those), mark the product `verified`, set the capture `processed`; with corrections the filed values stay in `proposed` |
| POST | `/proposals/{id}/reject` | Discard it and the capture; `409` when already decided |

Approving and rejecting are decisions: `write` + `approve`. Reading needs `read`.

### Agent

| Method | Path | Purpose |
|---|---|---|
| GET | `/agent/status` | Whether a queued run would be collected: `runner` is `ready`, `no_key` or `disabled`, with the model name only when ready. No key material is returned; the web app uses it to choose between **Process now** and the Claude hand-off (R67) |
| POST | `/agent/runs` | Queue a run on demand `{mode, captures[], from, to}` — the app's **Process now** button; `202 Accepted` with the run (`status: queued`); the worker picks it up within `agent.poll_seconds` (no cron needed) |
| GET | `/agent/runs?limit=&status=` | Runs with tokens, cost, summary |
| GET | `/agent/runs/{id}` | One run incl. `sessions[]` (one per drafted day) |
| POST | `/agent/runs/{id}/cancel` | Cancel a queued or running run; releases its locks |
| GET | `/agent/locks` | Current per-day locks (`date`, `runner`, `run_id`, `locked_until`) |
| DELETE | `/agent/locks/{date}` | Force-release a lock regardless of holder (operator escape hatch; scope `agent:write`) |

### Reports (Stage 2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/reports` | Built-in and tenant definitions |
| POST | `/reports/{name}/render?format=json|markdown&from=&to=&as_of=` | Render. `as_of` computes the whole report as of that day (R62); omitted means today |
| GET | `/reports/checkup` | Shortcut: built-in check-up, default window |

### Backup

Creating, verifying and restoring backups stays on the CLI (`victus backup …`, see
[BACKUP.md](BACKUP.md)); the API only shows what was recorded.

| Method | Path | Purpose |
|---|---|---|
| GET | `/backup/jobs?limit=20` | Recorded backups, newest first: scheduled runs, `victus backup create` and host backups that reported in with `victus backup record`. This tenant's jobs and the all-tenant ones. `limit` 1–200. Needs `admin` (`401` without a token, `403` for any other scope or a recovery session) |

Each job: `{id, tenant_id, started_at, finished_at, status, path, size, verified, error}`;
`status` is `running` | `finished` | `verify_failed` | `failed`, `tenant_id` is `null` for a
backup of every tenant, `size` is in bytes. There is no other route under `/backup`; the
former `501` placeholder is gone, so other paths answer `404`.

### System

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{status, version, checks, backup_age_hours, backup_last_at, backup_max_age_hours}` — no auth. `checks.backup` is `degraded` when no successful backup was ever recorded or the newest is older than `backup.max_age_hours`; `status` is `degraded` when any check is. Always `200` while the process answers |
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
