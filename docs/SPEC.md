# Victus — Specification

Victus is a self-hosted nutrition tracker: a database as the single source of truth, a REST API, a passkey-protected
Angular web app, a declarative report builder, an inbox for text/audio/photo captures that an AI agent turns into
day-log drafts, and an MCP server so an agent can drive all of it. Multi-tenant from the first schema, backup built in,
deployed as one Docker Compose stack.

This document is the contract. Requirements carry stable IDs (R*n*) and point at the module that implements them; design
decisions (D*n*) record *why* the contract looks the way it does. Terms are defined in [GLOSSARY.md](GLOSSARY.md).

## Purpose

The tracking Victus replaces lived in an Obsidian vault: Markdown day logs, a food table, recipes, a weight CSV, and a
handful of Python scripts that parsed all of it. Three salt definitions in three places, ten table-header variants,
fuzzy name matching instead of IDs, no automation, and every format change cost data. A previously used web app showed
the other failure mode: a web app without an API forces file-system workarounds.

Victus fixes both: **one database, one calculation, one API** — and every other surface (web, MCP, CLI, agent) is an
adapter on the same service layer.

## Scope and non-goals

| In scope | Out of scope (deliberately) |
|---|---|
| Food products, portions, recipes, cooked batches, day logs, meals, line items, weight, target bands | **Training logs** — stay in a dedicated training app; Victus only records a `training_type` marker per day |
| Import of an existing Markdown vault, repeatable, with a review list | **Weight measurement** — a scale app stays the source; Victus imports and allows *manual* corrections only |
| REST API, passkey login, API tokens, multi-tenancy | Diet advice, meal planning, shopping lists (may come later, not in Stages 0–3) |
| Reports and dashboards built from declarative definitions | Public SaaS operation — Victus targets a home server behind a VPN |
| Captures (text/audio/photo) → agent → **drafts** → human approval | Fully autonomous logging without approval |
| MCP server (stdio + Streamable HTTP) | A second write path around the service layer |
| Backup/restore with verification, Compose stack, runbooks | Cloud backup targets (a local path is enough; sync it with your own tooling) |

## Requirements

Column *Stage* refers to [PLAN.md](PLAN.md). *Where implemented* names the planned module; anything not yet in the
tree is marked **planned**.

### Data

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R1 | Nutrients are **never stored per line item**; they are computed from `base_quantity × nutrients-per-100` in database views (`line_item_macros`, `day_macros`) and in one pure function (`domain/services/nutrition.py`). Both are tested against each other. | `infrastructure/db/views.py`, `domain/services/nutrition.py` — planned | 1 |
| R2 | **Quantities freeze, nutrients propagate.** `line_item.base_quantity` is a historical fact and never recomputed; `product.*` nutrients are the current best estimate and a correction changes every historical day that references the product. | `domain/model/line_item.py` — planned | 1 |
| R3 | **Captured ≠ computed ≠ displayed.** A line item keeps the quantity as entered (`quantity` + `unit_code`), the frozen base quantity (`base_quantity` + `base_unit`) and an optional display override. | `domain/model/line_item.py` — planned | 1 |
| R4 | Every SQLite connection enables `PRAGMA foreign_keys = ON`; a test asserts it. PostgreSQL enforces FKs natively. | `infrastructure/db/engine.py` — planned | 1 |
| R5 | `consumable` is the supertype of `product`, `recipe_batch` and `ad_hoc_item`; `UNIQUE(id, kind)` plus composite FKs prevent a batch from posing as a product. | Alembic `0001_initial` — planned | 1 |
| R6 | `portion` is the **only** place holding piece weights; exactly one default portion per product and unit (partial unique index). | Alembic `0001_initial` — planned | 1 |
| R7 | A `recipe_batch` freezes total nutrients at cooking time; recipe edits never change past batches. | `application/use_cases/recipes.py` — planned | 1 |
| R8 | `target_band` is one row per complete profile, versioned by `valid_from`/`valid_to` and `training_type` (`rest`/`strength`/`martial_arts`); a `day_log` freezes its `target_band_id` on approval. | Alembic `0001_initial`, `domain/services/target_band.py` — planned | 1 |
| R9 | **Single salt source:** salt bands live only in `target_band`; no other configuration key defines salt targets. | `config/tenant_settings.py` (validation rejects `salt` keys elsewhere) — planned | 1 |
| R10 | `day_log.reliable` and `day_log.status` have **no defaults**. `reliable = false` means the *user* estimated the day wholesale; an agent estimate never lowers it. `status ∈ {draft, open, closed}`. Only `reliable = 1 AND status = 'closed'` days count for TDEE and reports (view `countable_days`). | Alembic `0001_initial`, `domain/model/day_log.py` — planned | 1 |
| R11 | Estimated line items are flagged (`estimated`, `quantity_estimated`) and rendered with ⚠️; the flag survives approval. | `domain/model/line_item.py`, `reports/render/markdown.py` — planned | 1 |
| R12 | Weight rows carry `source ∈ {scale_sync, manual, import}`; the API accepts and deletes only `manual` rows. | `application/use_cases/weight.py` — planned | 1 |

### Import

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R13 | **Victus has no importer** (ADR 0011). Existing data enters through the backup format: an external tool produces a Victus backup archive (JSONL per table, ADR 0008) and `victus backup restore` loads it; alternatively data is written through the REST API or the MCP tools. | `backup/restore.py`, `docs/MIGRATION.md` | 1 |
| R14 | The archive contract (table order, required columns, id rules, tenant scoping) is documented so third parties can write their own migration; `victus backup verify` validates an archive against the current schema before anything is written. | `docs/MIGRATION.md`, `backup/verify.py` | 1 |
| R15 | The generic building blocks a migration needs — quantity parser, unit table, three-stage product matcher — are part of the domain and reused by product search and agent drafts. | `domain/services/quantity_parser.py`, `units.py`, `matching.py` | 1 |

### Search

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R18 | Product and recipe search combines full-text (SQLite FTS5 / PostgreSQL `pg_trgm`) with the fuzzy matcher; **one** function serves web, API, and agent. | `infrastructure/db/search.py`, `application/use_cases/products.py` — planned | 1 |

### API

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R19 | REST under `/api/v1`, OpenAPI 3.1 generated, problem+json errors (RFC 9457). | `api/app.py`, `api/errors.py` — planned | 1 |
| R20 | The tenant is derived from the authenticated principal, never from the URL. | `api/deps.py` — planned | 1 |
| R21 | Every write endpoint runs exactly one use case in exactly one transaction (`UnitOfWork`). | `application/ports/unit_of_work.py` — planned | 1 |
| R22 | The Angular client is generated from `/openapi.json`; CI fails when the generated client drifts. | `web/src/app/api/`, `.github/workflows/web.yml` — planned | 1 |

### Auth and tenancy

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R23 | Browser login is **passkey only** (WebAuthn, `py_webauthn`); server-side sessions in HttpOnly/Secure/SameSite=Lax cookies with a CSRF header on writes. | `infrastructure/auth/webauthn.py`, `sessions.py` — planned | 1 |
| R24 | `RP_ID` is pinned when the first passkey is registered; the server refuses to start if the configured `RP_ID` differs from the pinned one. | `infrastructure/auth/webauthn.py` startup check — planned | 1 |
| R25 | The UI nudges until ≥ 2 passkeys exist; a one-time recovery code (Argon2 hash) allows passkey re-enrolment. | `web/features/auth`, `application/use_cases/auth.py` — planned | 1 |
| R26 | API tokens: 32 random bytes, shown once, stored as SHA-256, prefix `vct_`, scopes, mandatory expiry ≤ 365 days, revocable. | `infrastructure/auth/tokens.py` — planned | 1 |
| R27 | Every tenant-owned table has `tenant_id NOT NULL`; repositories scope automatically via `TenantContext`; PostgreSQL additionally gets row-level security. | `infrastructure/db/repositories/`, Alembic (postgres-only RLS) — planned | 1 |
| R28 | Every router has a test that accesses another tenant's resource and expects 404. | `tests/integration/api/` — planned | 1 |

### Web app

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R29 | Angular (standalone components, signals), Angular Material, ECharts; features: login, day log (day/meal/item), products, recipes, drafts & approval, weight (manual entry), reports, captures upload, settings, tokens. | `web/src/app/features/` — planned | 1–3 |
| R30 | The review list is a working view in the app (re-assign an `ad_hoc_item` to a product; quantity stays, nutrients propagate). | `web/features/products`, `application/use_cases/day_log.py::ReassignLineItem` — planned | 1 |

### Reports

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R31 | Reports are **declarative** YAML documents validated by `schemas/report-definition.schema.json`; blocks: `kpi_tile`, `band_distribution`, `tdee_windows`, `trend`, `forecast`, `burndown`, `weekly_chart`, `day_list`, `text_finding`. | `reports/engine.py`, `reports/blocks/` — planned | 2 |
| R32 | One engine renders to JSON (web), Markdown (chat, vault) and optionally SVG. | `reports/render/` — planned | 2 |
| R33 | The built-in `checkup` report reproduces the predecessor's status script and dashboard pages; TDEE, trend, forecast and burndown match frozen reference values within ±1 kcal / ±0.01 kg. | `reports/builtin/checkup.yaml`, `tests/fixtures/tdee_reference.json` — planned | 2 |
| R34 | TDEE is computed two ways on purpose — weekly and rolling windows — and each rolling window carries a quality grade (red/yellow/green) from coverage and length. | `domain/services/tdee.py`, `reliability.py` — planned | 2 |

### Captures and agent

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R35 | A capture is text, audio or image with a content hash unique per tenant; re-uploading the same content is a no-op. | `application/use_cases/captures.py` (`UploadCapture`), `api/routers/captures.py` | 3 |
| R36 | Audio is transcribed through a `TranscriptionPort` (first adapter: OpenAI `gpt-4o-transcribe`, configurable language and tenant vocabulary prompt). | `application/ports/transcription.py`, `infrastructure/transcription/openai_transcribe.py`, `application/use_cases/captures.py::TranscribeCapture` | 3 |
| R37 | The agent produces **drafts** (`day_log.status = 'draft'`, `line_item.is_draft = 1`) with confidence, reasoning, source capture and top-3 alternatives per item; it never approves. | `application/use_cases/agent.py::CreateDraft`, `agent/runner.py`, `schemas/agent-draft.schema.json` | 3 |
| R38 | Approval (`ApproveDay`) applies corrections, clears draft flags, freezes the `target_band_id`, marks captures processed, and records every change in `audit_log`. It is reachable from the web app and from the MCP tool `day_approve` after a chat summary. | `application/use_cases/drafts.py::ApproveDay`, MCP `day_approve` (`mcp/tools.py`), `web/features/drafts` | 3 |
| R39 | Two runners — an in-house worker (Anthropic SDK tool loop + API key) and an external Claude (Claude Code / claude.ai via MCP over HTTP) — share **one** `agent_lock (tenant_id, date)` table; write tools require a live `run_id` holding the lock. | `infrastructure/db/repositories/inbox.py::AgentRepo.try_acquire_lock`, `application/use_cases/agent.py::BeginAgentRun`/`CreateDraft`, `mcp/tools.py` | 3 |
| R40 | Every run records model, prompt version, tokens, cost and a Markdown summary in `agent_run`; budgets (tokens, USD, images) abort a run gracefully. | `agent/budget.py`, `agent/pricing.py`, `application/use_cases/agent.py::RecordAgentSession`/`FinishAgentRun` | 3 |
| R49 | **One day, one model session.** Each day is drafted in a fresh conversation containing only that day's captures; a run over several days executes one isolated session per day, sequentially. Day assignment of captures happens before drafting. `agent_session` records model, tokens, cost and outcome per day. | `agent/runner.py` (one conversation per day), `application/use_cases/agent.py::GetDayContext`, `mcp/tools.py` (`captures_open` scoped to the run's locked days) | 3 |
| R50 | Agent runs start **on demand**: `POST /agent/runs` (the web app's "Process now" button) queues a run the worker picks up within seconds; the cron schedule is optional and can be disabled (`agent.cron: null`). | `api/routers/agent.py`, `application/use_cases/agent.py::QueueAgentRun`, `agent/worker.py` | 3 |
| R52 | A capture may be attached to **one product** instead of a day (`capture.product_id`: label photo, spoken correction). It never joins a day thread; the agent processes it in a separate step (`captures_open scope=product` → `product_update` with `source` → `capture_mark processed`); corrected values propagate to every logged quantity of that product. | `application/use_cases/captures.py`, `mcp/tools.py` (`product_update`), `web/features/products/product-detail.ts`, migration `0002_capture_product` | 3 |
| R57 | A report can be **frozen as a snapshot**: its numbers are stored with the date they were computed and never change again. One written assessment belongs to each snapshot (the agent's, or the user's own note); snapshots are listed and read back per report. | `application/use_cases/snapshots.py`, `api/routers/reports.py`, `mcp/tools.py` (`report_snapshot_create`, `report_assess`), migration `0004_report_snapshot` | 2–3 |
| R58 | A tenant may keep **several goals**; exactly one is active and drives every report. The single `goal` object stays in sync with the active entry for readers of the old shape. | `schemas/tenant-settings.schema.json`, `infrastructure/reports/sqlalchemy_source.py::active_goal`, `web/features/settings` | 2 |
| R64 | A capture may carry **several files** (`capture_attachment`): photos, a voice note and a line of text taken together stay one capture, so their shared context survives. `capture.attachment_id` keeps pointing at the first file. | `application/use_cases/captures.py`, migration `0006_capture_attachment`, `web/shared/capture-input.ts` | 3 |
| R65 | **One capture, one form.** Text, photos and a voice note are not separate ways to save something: every screen offers a single text box next to the record, camera and file buttons, and a single "Save capture" button that sends whatever has been gathered. Text on its own is a capture; a day's note is the same thing as a day capture. | `web/shared/capture-input.ts`, `web/features/inbox/inbox-page.ts`, `web/features/days/day-thread.ts` | 3 |
| R66 | **Processed captures are cleaned up.** A capture that became line items is kept for `captures.processed_retention_days` (default 10, `0` keeps it for ever) and is then deleted together with every file only it referenced. Discarded captures keep their one-day window. The worker does this each tick, and listing captures does it too, so a deployment without a worker still tidies up. | `application/use_cases/captures.py` (`purge_settled`), `agent/worker.py`, `schemas/tenant-settings.schema.json` | 3 |
| R67 | **Never queue a run nobody collects.** `GET /agent/status` reports `ready`, `no_key` or `disabled` without exposing key material. With a runner the inbox keeps **Process now**; without one the button becomes **Open Claude for Processing** and hands a day-agnostic instruction to the user's own Claude over MCP, with a copy button beside it because a deep link may open in a browser rather than the app. Frozen report moments awaiting a judgement are listed on the same screen with the same hand-off. | `api/routers/agent.py`, `web/core/claude-handoff.ts`, `web/features/inbox/inbox-page.ts` | 3 |
| R68 | **One icon set, and a phone bar that stays put.** Navigation and the capture buttons use [Lucide](https://lucide.dev) (MIT) drawn from the package's own path data, so entries are legible in the collapsed rail. On a phone the rail is replaced by a fixed bar holding Today and four sections, with the rest behind **More**: nothing scrolls sideways and the bar does not move with the page. | `web/shared/icon.ts`, `web/app.html`, `web/app.scss` | 3 |
| R69 | **A day is local.** Timestamps stay in UTC, but every derivation of a calendar day goes through the configured zone (`regional.timezone`, default `Europe/Berlin`): today, the day a weigh-in or capture counts on, report anchors, and the app's date fields. Numbers and dates are written in `regional.locale` (default `de-DE`, so 1.234,5). Both are set per tenant and fall back to the server configuration. | `domain/services/calendar.py`, `application/use_cases/settings.py` (`regional_of`), `web/core/format.service.ts` | 3 |
| R70 | **A product's values may change over time.** A product carries `valid_from` / `valid_until` (null = still current) and `supersedes_id`. A new version copies the old row with its portions, starts open ended and closes its predecessor the day before, so days already logged keep the numbers that were true then. Search collapses each chain to the version that applied on `on` (default: the current one), and the day view passes its own date. The history stays a line: only the newest version can be continued. | `application/use_cases/products.py` (`NewProductVersion`, `valid_on`), migration `0007_product_validity`, `web/features/products/product-detail.ts` | 3 |
| R71 | **A finding is a judgement, not a log.** The `text_finding` block, titled **Assessment**, shows the assessment of the most recently assessed snapshot. It used to show the last agent run's summary, which describes what the agent did with the captures and says nothing about where the numbers stand. Without an assessment the block explains how to get one: freeze the report, then have it judged. | `infrastructure/reports/sqlalchemy_source.py` (`latest_finding`), `reports/blocks/_meta.py` | 3 |
| R72 | **The worker can judge frozen reports.** Run mode `assess` (migration 0008) takes the snapshots waiting for an assessment instead of days, one short model session each, and locks no day: the figures are already fixed, so it cannot collide with drafting. The frozen result goes into the prompt so the judgement is about that moment rather than today. With a runner the inbox offers **Assess now**, one run for all of them; without one it keeps handing over to the user's Claude. | `agent/runner.py` (`_assess_run`, `run_snapshot_assessment`), `agent/prompts/assess.md`, migration `0008_assess_run_mode` | 3 |
| R73 | **A unit is only offered if it has a size, or its size is asked for.** The unit picker on a day splits into weight and volume, the portions this product has, and count units it has no portion for. Choosing one of the last kind asks what one of them holds; the answer is stored as a portion of that product and used for the item, so the unit works from then on. Before this, picking such a unit was accepted by the form and rejected on save with "no portion for unit". | `web/features/days/day-view.ts` | 3 |
| R74 | **The portion form asks in words.** It offered a free-text label and a free-text "unit code", which required knowing the unit table by heart. The unit is now picked from the count units, the size reads "one bag of this is …", the name is optional and defaults to the unit's own word, and the form explains what **Use by default** decides. The product page's version button reads "Values changed…" rather than naming a field. | `web/features/products/product-detail.ts` | 3 |
| R76 | **Body measures beside the weight.** `body_measurement` holds tape-measure sessions (waist, belly, hip, chest, neck, thigh, arm, optional body fat), every value optional because people measure what they measure. Pure domain functions derive BMI with the WHO classes, waist-to-height against the NICE scale, waist-to-hip against the sex-specific WHO thresholds, and split a measured expenditure into resting rate (Mifflin-St Jeor) and activity, flagging an implausible activity level rather than presenting it. Height, sex and birth date come from the tenant settings and may be missing; a figure that needs them says which one is absent. Sessions can be recorded through the API, the MCP (`body_add`) and a capture, since a spoken list or a photo of a tape is a capture like any other. | `domain/services/body.py`, `application/use_cases/body.py`, migration `0009_body_measurement`, `mcp/tools.py` | 3 |
| R77 | **A class is shown with its scale.** The body block draws the whole range as segments, marks the class the value sits in and pins the value itself, and lists the BMI classes as weights with the current one highlighted. The weight chart shades the same classes behind the curve once a height is known, because the same 96 kg is one class at 170 cm and another at 190. Circumferences are entered on the weight page and shown with their change, a shrinking waist reading as an improvement. | `web/features/reports/report-blocks/report-block.ts`, `web/features/weight/weight-page.ts` | 3 |
| R78 | **The interface language is switchable at runtime.** `regional.language` (`en`, `de`, `es`, `fr`) changes the interface without a rebuild, kept separate from `regional.locale`, which only decides how numbers and dates are written, so German numbers with an English interface is a valid combination. The English string is its own key, so a missing translation falls back to correct English rather than showing a key; `scripts/check_translations.py` reports the gaps so the fallback does not become permanent. | `web/core/i18n.service.ts`, `web/core/i18n.de.ts`, `web/core/i18n.es.ts`, `web/core/i18n.fr.ts`, `scripts/check_translations.py` | 3 |
| R79 | **A status message floats above the page.** Saving happens at the bottom of a long form, so a confirmation rendered at the top of it is never seen and the save looks like it did nothing. `NoticeService` plus `v-notices`, mounted once in the shell, show successes and errors at any scroll position, above the phone tab bar. A success disappears by itself; an error stays until dismissed, because it says something to act on. An inline error is kept only for lasting page state, never for an event. | `web/core/notice.service.ts`, `web/shared/notices.ts` | 3 |
| R80 | **Body measurements read as measures down, sessions across.** Seven measures against two or three sessions do not fit a row-per-session table, and it broke into odd columns. The table is transposed, at most four sessions shown newest first, with the change between the two newest. A measure nobody taped is dropped rather than shown as a row of dashes, and a gap on either side stays a dash instead of becoming a change of zero. The measure column is sticky, so it survives sideways scrolling on a phone. | `web/features/weight/weight-page.ts` | 3 |
| R62 | Every report is computed **as of one day** (`as_of`, default today): rolling windows, forecasts and the burndown end there, and the period ends there too, so the panels and the tables agree. | `api/routers/reports.py`, `mcp/tools.py` (`report_render`, `report_snapshot_create`), `web/features/reports` | 2 |
| R63 | The `timeline` block puts weight, intake, the rolling TDEE and the macro split on one shared time axis, one row per day, so they can be read together. | `reports/blocks/timeline.py`, `schemas/report-definition.schema.json`, `web/features/reports/report-blocks` | 2 |
| R61 | The user can write **rules** in their own words (when → then, per scope), in the app or in a chat. Rules live in the versioned tenant settings and are handed to the agent with every drafting and product session; they take precedence over the agent's own judgement. | `application/use_cases/rules.py`, `api/routers/settings.py`, `mcp/tools.py` (`rules_list`, `rule_upsert`, `rule_delete`), `agent/runner.py::tenant_rules` | 3 |
| R60 | A product shows where it was eaten: the days it was logged on with amount, kcal and draft state; every logged item links back to its product. | `application/use_cases/products.py::GetProductUsage`, `api/routers/products.py`, `web/features/products/product-detail.ts` | 1 |
| R59 | Every logged item shows a small icon: the product's own `icon` wins, otherwise one guessed from the product name, then the category, then the consumable kind. | `product.icon` (migration `0005_product_icon`), `web/shared/food-icon.ts` | 1 |
| R56 | A draft can be accepted **item by item** or as a whole; a day leaves `draft` status when its last drafted item is accepted, and a capture stays reviewable until every item it produced has been decided. | `application/use_cases/drafts.py::ApproveLineItem`, `api/routers/drafts.py`, `mcp/tools.py` (`line_item_approve`), `web/features/inbox` | 3 |
| R54 | The agent never writes product values directly: a product capture becomes a **proposal** (`product_proposal`) that a person approves or rejects; approving applies it, marks the product `verified` and the capture `processed`. | `application/use_cases/proposals.py`, `api/routers/proposals.py`, `mcp/tools.py` (`product_propose`), migration `0003_product_proposal` | 3 |
| R55 | Captures can be deleted while unused (`new`, `failed`, `discarded`), restored after a discard, and are purged automatically one day after being discarded; an unintelligible transcript (empty, or an echo of the vocabulary prompt) marks the capture `failed` instead of feeding the prompt to the agent. | `application/use_cases/captures.py::DeleteCapture`/`purge_discarded`/`looks_like_prompt_echo` | 3 |
| R53 | Meals can be renamed and re-timed; a meal is deleted only when it has no line items (`409` otherwise). | `application/use_cases/day_logs.py::UpdateMeal`/`DeleteMeal`, `api/routers/days.py`, `mcp/tools.py` (`meal_update`, `meal_delete`) | 3 |
| R51 | Every day owns a **resumable thread** of user captures and agent messages (`day_message`). New messages — before, during or after processing — join that day's context only; a message on a drafted or locked day queues a `follow_up` run that changes the draft incrementally. Agent questions are thread messages; replies follow the same path. | `application/use_cases/day_logs.py::GetDayThread`/`AddDayMessage`, `application/use_cases/captures.py::queue_follow_up_if_needed`, `api/routers/days.py`, `mcp/tools.py` (`day_thread_get`, `day_message_add`) | 3 |

### MCP

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R41 | The MCP server calls the **service layer directly**; it exposes read, write, approve, capture and agent tools with scopes, over stdio (`victus mcp --tenant`) and Streamable HTTP (`/mcp`, bearer token, rate limit, VPN CIDR only). | `mcp/server.py` (stdio, `mount_http`), `mcp/tools.py` (registry), `cli/agent_cmd.py` (`victus mcp`) | 3 |

### Configuration

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R42 | Server configuration (`victus.yaml` + `VICTUS_*` env) is separate from **versioned** tenant settings (`tenant_settings`, JSON-schema validated). Precedence: env > yaml > defaults. | `config/server.py`, `config/tenant_settings.py` — planned | 1 |

### Backup

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R43 | `victus backup create|verify|restore|schedule`: a ZIP with `manifest.json` (counts, SHA-256 per file), one JSONL file per table, blobs by hash, optional SQLite snapshot. `verify` restores into a temporary database and compares counts. Retention 7 daily / 8 weekly / 12 monthly. `/health` reports `backup_age_hours`. | `backup/` (`export`, `verify`, `restore`, `retention`, `schedule`) | 1 (create/verify), 3 (schedule) |

### Operations

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R44 | The complete stack ships in `deploy/docker-compose.yml` (api, web, worker, backup; profiles `postgres`, `caddy`, `dev`) with shell wrappers for backup and restore that need no Python knowledge. | `deploy/` | 0 |
| R45 | Runbooks exist for backup/restore, incidents, migration and deployment; the test plan lists every test case with an ID. | `docs/BACKUP.md`, `OPERATIONS.md`, `MIGRATION.md`, `DEPLOYMENT.md`, `TESTPLAN.md` | 0 |

### Quality

| ID | Requirement | Where implemented | Stage |
|---|---|---|---|
| R46 | CI: pytest on Python 3.12–3.14 against SQLite and PostgreSQL, ruff, mypy (strict for `domain` and `application`), pip-audit, Trivy, CodeQL, Angular build + unit tests, Docker build, OpenAPI client drift check. | `.github/workflows/` | 0–1 |
| R47 | Domain services are pure functions with no I/O; reference and golden tests live in `tests/fixtures/`. | `tests/unit/domain/` — planned | 1–2 |
| R48 | The repository contains no personal or health data: examples use placeholder tenants, domains and values; fixtures are synthetic or anonymised. | `tests/fixtures/`, `examples/`, CI secret scan | 0 |

## Design decisions

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Hexagonal architecture** (domain → application → adapters). | Four primary adapters (REST, MCP, CLI, agent) must run the same use cases with the same authorisation. Putting logic in routers would duplicate it four times. See [ADR 0001](adr/0001-hexagonal-architecture.md). |
| D2 | **SQLite first, PostgreSQL ready.** | A home server with one household does not need a database server; SQLite in WAL mode is enough. Dialect-neutral SQLAlchemy plus Alembic keeps the switch a config change, and CI runs both. See [ADR 0002](adr/0002-sqlite-first-postgres-ready.md). |
| D3 | **Drafts plus approval through a chat summary.** | The previous workflow never skipped the human confirmation step, and a mis-logged day silently distorts TDEE. The agent writes drafts; the user approves after a compact summary — in chat or in the app. See [ADR 0003](adr/0003-drafts-and-chat-approval.md). |
| D4 | **MCP calls the service layer, not the REST API.** | Calling one's own HTTP API means self-authentication and double serialisation. Authorisation lives in the use case anyway, so REST and MCP are checked identically. See [ADR 0004](adr/0004-mcp-calls-service-layer.md). |
| D5 | **Two agent runners, one lock table.** | Users want both an API-key worker and the ability to drive processing from an existing Claude subscription. Both go through the same use cases and the same `agent_lock`, so a day is never drafted twice. See [ADR 0005](adr/0005-two-agent-runners-one-lock.md). |
| D6 | **`RP_ID` pinned at the first passkey.** | Changing the WebAuthn relying-party ID invalidates every passkey. Victus stores the ID on first registration and refuses to start with a different one. See [ADR 0006](adr/0006-rp-id-pinned.md). |
| D7 | **Salt targets live only in `target_band`.** | The predecessor held three contradicting salt definitions. One versioned table per training type ends that. See [ADR 0007](adr/0007-single-salt-source.md). |
| D8 | **Backup format: JSONL per table + blobs + manifest.** | Dialect-neutral, diffable, inspectable with standard tools, restorable row by row. A SQLite snapshot is optional extra, never the primary format. See [ADR 0008](adr/0008-backup-format-jsonl.md). |
| D9 | **English identifiers everywhere; the glossary maps the German source vocabulary.** | The importer reads German Markdown, but the product is public and its API, schema and tools must read naturally to any contributor. |
| D10 | **Angular for the web app.** | Standalone components and signals keep it lean; the client is generated from OpenAPI so the API stays the contract. |
| D11 | **Tenant from the auth context, not the URL.** | URL tenants invite IDOR mistakes; a session or token already knows its tenant. |
| D12 | **Transcription behind a port.** | Whisper today, a local model tomorrow; the agent must not care. |
| D13 | **Nutrients as views and as one pure function.** | Views give the database one calculation for reports; the pure function gives drafts and previews the same numbers without a round trip. Tests pin them to each other. |
| D14 | **Declarative report definitions.** | The predecessor's dashboards were hundreds of `append()` calls in one script. A YAML definition plus typed blocks makes reports composable and lets users build their own check-up. |
| D15 | **Compose stack in the repository.** | The deployment is part of the product: api, web, worker, backup and optional postgres/caddy start with one command. |
| D16 | **No personal data in the repository.** | Victus is public. Examples, fixtures and docs use placeholders; real data lives only on the operator's server and in backups. |
| D17 | **One model session per day.** | A long context that carries yesterday's guesses into today produces confident-looking errors and grows cost with every day. Fresh sessions keep each draft small, reproducible and independently auditable; shared knowledge is fetched through tools from the database instead (ADR 0009). |
| D18 | **A conversation thread per day.** | Logging is incremental — a note at breakfast, a photo at lunch, a correction at night. Seeding each per-day session with the day's thread gives continuity without breaking day isolation (ADR 0010). |
| D19 | **Source available, not open source.** | Anyone may run Victus for themselves or their household; selling it and hosting it for money stay with the copyright holder. PolyForm Noncommercial states exactly that, indefinitely. Permissive licences allow closed forks and paid hosting by anyone, and AGPL still allows charging for hosting. The Open Source Definition forbids restricting commercial use, so this is deliberately not an open-source licence (ADR 0012). |

## Data model (overview)

Migration `0001_initial` (planned, Stage 1) creates the tables below. Columns are listed in [ARCHITECTURE.md](ARCHITECTURE.md) and the Alembic file.

| Table | One line |
|---|---|
| `tenant`, `user`, `passkey_credential`, `session`, `api_token` | Tenancy and authentication |
| `tenant_settings` | Versioned JSON settings per tenant |
| `unit` | Global unit master data (mass / volume / count) |
| `category` | Product categories per tenant |
| `consumable` | Supertype of everything a line item can reference |
| `product`, `portion` | Products with nutrients per 100 g/ml; portions with piece weights |
| `recipe`, `recipe_ingredient`, `recipe_batch` | Recipe definition, ingredients, and cooked batches with frozen totals |
| `ad_hoc_item` | One-off items (restaurant, unmatched import rows) |
| `target_band` | Target-band profiles per training type, versioned |
| `day_log`, `meal`, `line_item` | Day log → meals → line items (frozen base quantity) |
| `weight_entry` | Weigh-ins with source |
| `capture`, `attachment`, `transcript` | Inbox items, attachments, transcripts |
| `agent_run`, `agent_session`, `agent_lock` | Agent job protocol, one session record per day, per-day locks (5-minute TTL) |
| `day_message` | The agent side of a day's thread (summaries, questions, notes); captures are the user side |
| `backup_job`, `audit_log` | Backup protocol and change audit |
| Views `consumable_per100`, `line_item_macros`, `day_macros`, `countable_days`, `source_check` | The one place where nutrients are calculated |

## Glossary

See [GLOSSARY.md](GLOSSARY.md) — including the German terms of the source vault the importer reads.
