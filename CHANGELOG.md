# Changelog

All notable changes to Victus are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Licensed under **PolyForm Noncommercial 1.0.0** (ADR 0012): every noncommercial use is granted,
  including running it for yourself or your household and use by charities, schools and public
  health or research organisations. Selling the software or a derivative, and running it as a paid
  or hosted service for other people, need a separate licence from the copyright holder. This is
  deliberately not an open-source licence. `CONTRIBUTING.md` carries the contributor agreement that
  keeps the project licensable as a whole.
- Stage 1: persistence layer (29 tables, 5 nutrient views, Alembic migration with unit seed, tenant-scoped
  repositories), use cases, REST API under `/api/v1` (products, portions, recipes, batches, days, meals,
  line items, drafts and approval, weight, settings, target bands, day threads), WebAuthn passkeys with
  recovery codes, server-side sessions with CSRF, scoped API tokens, admin CLI (`migrate`, `tenant`,
  `user`, `token`, `passkey`), backup create/verify/restore/prune/schedule with JSONL archives.
- Stage 2: pure reporting domain (TDEE weekly and rolling, moving average, trend, forecast, burndown, band
  rating, reliability grade, day consistency checks) pinned to synthetic reference values; declarative
  report engine with nine block types, JSON and Markdown renderers, built-in `checkup`, `/reports` API.
- Angular web app: passkey login and recovery, days and day view with band gauges and day thread, drafts
  approval, products with review list, recipes, weight, captures with "Process now", settings (target
  bands, tokens, passkeys), reports dashboard with one component per block type.
- Domain services for product matching (three-tier), quantity parsing and the unit table; privacy check
  script and CI job (SPEC R48).
- Stage 3: captures (text, audio, image) with content-hash dedupe, attachments in blob storage, transcription
  port with the OpenAI `gpt-4o-transcribe` adapter (ffmpeg conversion, tenant vocabulary prompt); agent use
  cases (queue/begin/finish runs, per-day locks, day context, schema-validated `CreateDraft`, sessions); the
  in-house runner (Anthropic SDK tool loop, one model session per day, budget, pricing, prompt files with
  version hash) and the worker (queue consumer for **Process now**, optional cron, heartbeat); one tool
  registry serving the MCP server (stdio `victus mcp --tenant`, Streamable HTTP at `/mcp` with bearer scopes,
  CIDR allow-list and rate limit) and the runner; REST `/captures`, `/attachments/{id}`, `/agent/runs`,
  `/agent/locks`; CLI `victus agent run|runs|unlock`, `victus worker [--once]`, `victus mcp`; web: captures
  page with transcripts, media, set-day/discard/re-transcribe, Agent page with runs, sessions, summaries,
  cancel and force-unlock, day thread states.

- Meals can be renamed and re-timed (`PATCH /meals/{id}`) and deleted when empty (`DELETE /meals/{id}`, 409 otherwise);
  MCP tools `meal_update`, `meal_delete`.
- Product captures (R52): `capture.product_id` (migration 0002), `POST /captures` with `product_id`, list filter,
  MCP `captures_open(scope=product)` and `product_update`; product page section "Label photos & notes".
- Web: voice recording (MediaRecorder), "Take photo" and multi-file picker on the inbox, on every day thread and on
  products; images and audio shown inline; structured tenant settings form (JSON kept as advanced editor);
  appearance settings with light/dark pin and six colour palettes; navigation badges for new captures, drafts and
  open days; the second-passkey notice can be dismissed for good; phone layout pass (touch targets, scrollable
  tables, fewer macro columns); installable web manifest.

- Product proposals (R54): the agent proposes label readings (`product_propose`, `product_proposal` table,
  migration 0003) and a person approves or rejects them (`/proposals`, product page section); approving marks
  the product verified.
- Captures can be deleted while unused, restored after a discard, and are purged one day after being discarded;
  an empty or prompt-echo transcript marks the capture `failed` instead of passing the vocabulary prompt on (R55).
- Day threads carry their captures with media: audio players, image thumbnails and the same actions everywhere
  (one capture card for inbox, day and product).
- Web: Victus logo and favicon, collapsible navigation rail, configurable landing page after sign-in, pages
  centred on wide screens, badge for pending product proposals.

- Drafts can be accepted item by item (`POST /line-items/{id}/approve`, MCP `line_item_approve`) or as a whole (R56);
  a capture stays reviewable until every item it produced has been decided.
- One inbox screen replaces the separate capture and draft pages: each drafted item sits next to the capture it
  came from, with per-item and whole-day accept.
- Product proposals let you tick the fields to apply; line items carry their source capture and product category.
- Small category icons in front of every logged item, a redesigned sign-in page and readable agent summaries
  (wide markdown tables scroll instead of breaking).

- Report snapshots (R57): freeze a report's numbers as a moment, then attach one assessment
  (`/reports/{name}/snapshots`, `/reports/snapshots/…`, MCP `report_snapshot_create` and `report_assess`);
  the reports page lists moments and opens them in place.
- Several goals per tenant, exactly one active (R58); the settings form manages them with their stages.
- Products carry their own icon (R59), editable in a reworked product form; every logged item shows it.
- Burndown chart reworked: one dotted line per stage next to the goal line, a today marker, day/month
  axis labels and no more uneven sampling.
- Accepting a drafted item can move it to another meal or create one (`meal_id` / `meal_name`).
- Agent run details open below the table instead of beside it.

- A product page shows where it was eaten (R60): the days it was logged on with amounts, kcal and
  draft state; items in the day view link back to their product. MCP `product_usage`.

- Your own rules for the agent (R61): "when … then …" in your words, managed under Settings or in a
  chat (`/settings/rules`, MCP `rules_list`, `rule_upsert`, `rule_delete`); every drafting and product
  session gets them and follows them before its own judgement.
- Target bands are editable in the settings form instead of only as JSON.
- The check-up shows the TDEE windows 7, 14, 30, 60 and 90 days and the trend up to 90 days.
- Burndown tooltips answer the actual question: weight behind the remaining kilograms, distance to the
  goal, change since the day before, and how far ahead or behind each planned line you are.
- Readable wording for the TDEE reference basis, equal-height KPI tiles, and the custom date range no
  longer reflows the report controls.

- Reports are computed as of a chosen day (R62): the anchor drives every rolling window, so tables and
  charts agree; picking an earlier day shows the picture as it was then.
- New `timeline` block (R63): weight against the goal, intake against the corridor with the rolling TDEE,
  and the macro split, stacked on one time axis with a linked crosshair.
- The check-up covers the TDEE windows 7, 14, 30, 60 and 90 days.

- "Take photo" uses the webcam on a computer: a live preview with a shutter button, falling back to the
  file dialog when no camera is available. On phones it still opens the camera app.
  A rejected constraint is retried with a bare video request, because some desktop drivers refuse
  every constraint they do not know, and an insecure page now says so instead of reporting no camera.

- A capture can carry several files (R64, migration 0006): photos, a voice note and a typed line taken
  together stay one capture, so the agent sees them as one thing. The camera stays open for another
  picture, offers a camera switch and runs full screen on a phone; the tray shows what will be sent.

- One capture, one form (R65): the text box sits with the record, camera and file buttons behind a single
  "Save capture" button, on the inbox, a day and a product alike. Text on its own is a capture, so a day's
  note and a day capture are the same thing and the separate "Save text" and "Send" buttons are gone.

- Processed captures are cleaned up after `captures.processed_retention_days` (default 10, `0` keeps them
  for ever), together with the photos and recordings only they referenced (R66). The worker does it each
  tick, and listing captures does it too.

- The inbox stops queueing runs nobody would collect (R67): with a worker and a model key it keeps
  "Process now", otherwise the button reads "Open Claude for Processing" and hands the job to the user's
  own Claude over MCP, with a copy button beside it. Frozen report moments still waiting for a judgement
  are listed on the same screen with the same hand-off.

- Navigation and the capture buttons use the Lucide icon set instead of text glyphs (R68), so the
  collapsed rail is readable. On a phone the rail becomes a fixed bar with Today and four sections and a
  "More" sheet for the rest: nothing scrolls sideways and the bar no longer moves with the page.

- A day is local (R69). Timestamps stay in UTC, but today, the day a weigh-in or capture counts on, the
  report anchor and the app's date fields all follow `regional.timezone`, default `Europe/Berlin`. A
  reading just after midnight no longer lands on the day before. Numbers and dates are written in
  `regional.locale`, default `de-DE`, so 1.234,5 rather than 1,234.5. Both are per tenant with the
  server configuration as fallback, and editable under Region in the settings.

- A product's values may change over time (R70, migration 0007). A new version copies the product with
  its portions, starts open ended and closes the previous one the day before, so every day already
  logged keeps the numbers that were true then. The product page shows the values over time and can
  start a new version; the day view offers the version that applied on the day being logged. Two MCP
  tools, `product_versions` and `product_version_create`, do the same from a chat.

- The report's finding block is now titled **Assessment** and shows the judgement of the most recently
  assessed snapshot (R71). It used to show the last agent run's summary, which describes what the agent
  did with the captures rather than where the numbers stand. With no assessment yet, the block says how
  to get one.

- The worker can write those assessments itself (R72, migration 0008): run mode `assess` judges every
  frozen report that is waiting, one short session each, and locks no day. With a model key the inbox
  shows "Assess now"; without one it still hands the job to the user's own Claude.

- The unit picker on a day no longer offers units that cannot work (R73). It groups weight and volume,
  the portions a product has, and count units it has no portion for. Choosing one of the last kind asks
  what one of them holds and stores the answer with the product, instead of accepting the item and
  rejecting it on save with "no portion for unit".

- The portion form on a product asks in words instead of field names (R74): the unit is picked from a
  list, the size reads "one bag of this is …", the name is optional, and the form says what "use by
  default" decides. The button that records changed values reads "Values changed…".

### Changed
- No importer in the product (ADR 0011): existing data enters through the backup archive format, REST or MCP.
- One model session per day (ADR 0009) and a resumable per-day thread (ADR 0010); lock TTL 5 minutes;
  agent runs start on demand (`POST /agent/runs`), cron optional.
- Alpine base images pinned to the newest tags; GitHub Actions at current majors.
- Agent default model `claude-opus-5` with adaptive thinking (`agent.effort`, default `medium`); server-side
  refusal fallbacks on by default (`agent.fallbacks`); budget defaults 400k/40k tokens, 2 USD, 12 images per run;
  new keys `agent.poll_seconds`, `agent.max_tokens`, `agent.max_turns_per_day`, `agent.pricing`.
- The worker is a queue consumer: `POST /agent/runs` is processed within `agent.poll_seconds`; `agent.enabled`
  only controls the cron schedule.

### Stage 0
- Stage 0 scaffold: Python package (`victus` CLI, FastAPI factory, `/api/v1/health` and `/api/v1/version`),
  configuration loader (env > `victus.yaml` > defaults), Angular workspace under `web/`.
- Specification, architecture, configuration, API, reports, agent, MCP, deployment, migration,
  backup, operations and test-plan documents under `docs/`, plus ADRs 0001–0008.
- JSON Schemas for server config, tenant settings, report definitions, backup manifests and agent drafts.
- Docker Compose stack (`deploy/`) with api, web, worker, backup services and optional postgres/caddy profiles.
- CI (pytest 3.12–3.14 × SQLite/PostgreSQL, ruff, mypy), web, security, docker and release workflows.

[Unreleased]: https://github.com/Supportlik/victus/compare/main...HEAD
