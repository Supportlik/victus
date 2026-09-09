# Changelog

All notable changes to Victus are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-09-10

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

- Body measures beside the weight (R76, migration 0009): tape-measure sessions with waist, belly, hip,
  chest, neck, thigh and arm, every value optional. From them come BMI with the WHO classes,
  waist-to-height, waist-to-hip against the sex-specific thresholds, and a split of the measured
  expenditure into resting rate and activity that flags an implausible activity level instead of
  presenting it. Height, sex and birth date come from the settings and may be missing; a figure that
  needs them says which one is absent. Sessions arrive through the API, the MCP (`body_add`) or a
  capture, because a spoken "waist 126, hip 118" is a capture like any other.

- Saving the settings says so (R79). The confirmation used to render at the top of a long form while
  the button sits at its bottom, so a successful save looked like nothing happened. Messages now float
  above the page at any scroll position, above the phone tab bar; a success clears itself, an error
  waits to be dismissed. Every action on the settings page reports its failure the same way.
- The body measurement table reads measures down and sessions across (R80), the way the data is kept
  by hand, with the change between the two newest sessions. A measure nobody taped is left out instead
  of filling a row with dashes, and the measure column stays put while the sessions scroll.

- The interface speaks German or English, switchable in the settings without a rebuild (R78). The
  language is separate from the number format, so German numbers with an English interface is a valid
  choice. The English string is its own key, so an untranslated view reads as correct English rather
  than showing a key, and `scripts/check_translations.py` reports what is still missing. Translated so
  far: the shell and navigation, the day view, the inbox with the capture form, and the weight page.
  Products, recipes, reports, settings and the agent screen follow.

- Every class is shown with the scale around it (R77). The report's body block draws the full range,
  marks the class the value falls in and pins the value, and lists the BMI classes as weights with the
  current one highlighted. The weight chart shades those classes behind the curve once a height is
  known. Circumferences are entered on the weight page and listed with their change against the
  previous session.

- The server sends no finished sentences any more (R78). A day's findings, a report's
  notes, the reason a figure is missing and the caveat on an implausible energy split all
  travel as a key plus its parameters — `{"key": "{n} days left", "params": {"n": 79}}` —
  so the interface says them in its own language and writes the numbers in its own
  convention. Markdown and the CLI fill the same key in directly, so their English output
  is unchanged, and frozen snapshots keep the sentence they were frozen with.
  `scripts/check_translations.py` now reads both halves: the `i18n.t()` calls in the
  templates and the `Message(...)` keys in the Python source.
- Spanish and French join German and English (R78). The three dictionaries carry the same keys in
  the same order, `scripts/check_translations.py` checks every one of them, and the settings offer
  the language beside the number format, which stays a separate choice.

### Fixed
- A gap in a day means a macro nobody knows, not a macro nobody declared. The day check asked the
  declared source macros and then the balance table — both of which only exist on a day imported from
  the vault — and gave up, so every day logged in Victus itself reported "no value for kcal, protein,
  carbs, fat, fiber, salt" while its line items added up perfectly. The items are what such a day
  knows, and they are now the last source consulted before a gap is called.
- The BMI class table in a Markdown report says which number is a BMI and which is a weight. It
  printed `| normal weight | 18.5 kg | 25.0 kg |`: the class boundary carrying the kilogram suffix of
  the weight it corresponds to, so neither number could be read as what it is. Both scales travel with
  the mark (R82), so the table shows the BMI range, the kilogram range and the distance from here.
- "You are here" marks the class the reader is actually in. The row was found by comparing the weight
  against the *BMI* boundaries, and no weight is below 18.5 — so every class answered "not here"
  except the open-ended top one, which then marked itself whatever the reader weighs. It was invisible
  because the test fixture put kilograms in the BMI fields; the fixture now has the shape the server
  sends.
- Timestamps are shown on the clock the reader uses. The day thread and the capture card cut the hour
  out of the stored ISO string, which is UTC: at ten past one in the morning in Berlin the thread said
  23:12 and the card said the previous day. Both go through the tenant's zone now, like every other
  time in the app.
- A portion label no longer carries the language of whoever typed it. Declaring "1 Tüte = 500 g" in
  the German app wrote the German word into the database, so the same portion read "Tüte (500 g)" in
  the English app while one declared over MCP read "tub (150 g)" in the German one. The row keeps the
  unit's own word — the key the table row already translates — and the list translates it on the way
  out.
- Four sentences reached a German reader in English: the two the inbox shows when the agent is off
  were chosen by a ternary *inside* `i18n.t(...)`, and the frozen-report line joined two raw ISO dates
  with a literal "to". The translation check now reads the whole first argument of a call, so a key a
  ternary picks counts like any other — and it no longer mistakes the condition of that ternary, or a
  nested call's arguments, for keys. It had also been cutting an argument at the first comma, sentence
  or not, which hid 46 keys from the check.
- The BMI bands in the weight chart are translated. The chart carried its own spelling of the scale
  ("obesity III"), which is not the domain's name ("obesity class III") and so had no dictionary entry
  to find; the shading, the weigh-in dots and the moving average now name themselves in the reader's
  language.
- Taking a draft over refreshes what it changed. Approving marks the capture processed and empties the
  inbox, but only the meal tables were refetched, so the capture card kept its "in draft" badge and the
  inbox its count until the page was reloaded by hand.
- The product search takes the caret when it opens. It appears only because someone chose to search,
  and it is inserted after the click — too late for the `autofocus` attribute to do anything.
- Revision 0010 checks for its constraints the way it checks for its columns. Revision 0001 builds the
  schema from the mapped models, so a fresh database arrives already carrying `kind`, `consumable_id`,
  their CHECK and their foreign key; creating the two named constraints unconditionally failed every
  PostgreSQL run with `constraint "ck_product_proposal_kind" ... already exists`, invisible on SQLite
  because that dialect never reaches the branch.
- A KPI note in a rendered Markdown report is a sentence again. Since the server started sending
  keys and parameters instead of prose (R78), the Markdown renderer printed the object itself —
  `Message(key='{n}-day moving average', params={'n': 7})` — in every report an agent or the CLI
  reads. The other message fields were already filled in; only the KPI note was missed.
- Choosing a unit the product has no portion for asks what it holds again. The chosen unit was a
  plain field read inside a `computed()`, so picking "bag" never re-evaluated the question — the
  field stayed hidden and the item was refused on save with "no portion for unit". A product is now
  also offered only the units of its own reference family: a product declared per 100 g carries no
  density, so millilitres are not something it can be measured in.
- "Nothing found" waits for an answer. The empty state was tied to the result list alone, so it
  appeared during the debounce and while the request was in flight: a search for two words claimed
  nothing was found while five products were on their way.
- A wide table no longer stretches the page. Every data table sits in its own horizontal scroller and
  single-column grids have a floor of zero, so a phone no longer scrolls sideways and takes the tab
  bar with it. The mobile table hack that made a table shrink to its content — rows ending two thirds
  across the panel with the head rule running past them — is gone with it.
- Switching light and dark repaints everything. Chrome keeps the pre-switch value of any transitioned
  property whose colour comes from a custom property, so the rail and the phone bar stayed in the old
  scheme until the next reload. The appearance change now runs with transitions suspended for a frame,
  which also removes the page-wide colour fade.
- Labels can be read on every palette. The meaning colours have text variants (`--v-*-ink`): amber on
  pale amber measured 1.9:1 in the light schemes, and a link in dark mode 2.5:1. Table heads moved from
  the faintest ink to the middle one, and the primary button's white sits on a shade deeper than the
  plain accent.
- The report's body block reads left to right: the measure, then its figure, then the class it falls
  in. The class the value falls in is no longer filled white — the pin says where it is — the segment
  colours follow what each class means instead of an invented ramp, and the kilogram table with the
  BMI range and the distance to each class is shown rather than folded away.
- The day page on a phone: the three loose day links became one pill with thumb-sized ends, a meal's
  actions stay together on their own row instead of leaving "Delete" mid-panel, and page heads stack
  with full-width controls. Day names and every number follow the tenant's locale.
- The browser tab icon is legible on a dark tab strip: the plate of `favicon.svg` follows the
  browser's own theme.
- `victus token revoke` takes the prefix that `victus token list` prints, not only the internal id.

### Changed
- **`write` proposes, `approve` decides** (ADR 0013, R81). The approve scope guarded `day_approve`,
  `line_item_approve` and `draft_discard`, but a token with plain `write` reached the same end state
  around them: `line_item_create` wrote finished items, `line_item_delete` discarded drafts one by
  one and removed approved ones, `close_day` and `reliable` moved a day into the TDEE series, the
  catalogue was writable outright, and a proposal could be decided. Now an actor without `approve`
  adds items **as drafts**, may withdraw only its own draft (`agent:write`), and cannot touch what a
  person approved; catalogue writes and proposal decisions need `approve`. A browser session is
  unaffected — it holds every scope.
- A product the agent has never seen no longer has to be invented into the catalogue: `product_create`
  without `approve` files a **`kind='new'` proposal** and returns `log_against_consumable_id`, a one-off
  consumable the day can log at once with correct macros. Approving it in the app **promotes** that
  consumable into the product, keeping its id — every line item already logged against it stays
  exactly as it was and the product becomes searchable. Rejecting leaves the meal untouched and the
  catalogue clean. Proposals now carry portions too, so the tub or can a product comes in arrives with it.
- The timeline tooltip shows the weigh-in beside the 7-day average instead of only one of them, so a
  day's reading on the scale can be read against the trend.
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
