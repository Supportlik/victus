# Changelog

All notable changes to Victus are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.6.0] - 2026-09-10

### Added
- A security policy ([`SECURITY.md`](SECURITY.md)): where to send something exploitable, what
  happens then, and what is in scope — authentication, tenant isolation, the REST and MCP
  surfaces, the agent path, the shipped Compose defaults — as against a deployment that changed
  the configuration or a scanner report with no reachable path. The privacy check allows the
  maintainer's address there for the same reason it allows it in the licence: a policy with no
  address nobody can reach is not a way to report anything.

### Fixed
- Three claims in the showcase that the pictures do not support: the colour scheme follows the
  device and there are six palettes to pin instead of one dark mode; the catalogue's source
  column is a badge (label or estimate) *and* the text of where the number came from, not a
  single field; and the check-up does print a reference TDEE — what it adds is which window that
  came from and how far each of the others can be trusted. A tour that overstates what a picture
  shows is worse than no tour.

## [1.5.1] - 2026-09-10

### Fixed
- **A silent recording was stored as the vocabulary prompt: seventy words of exercise and
  food names, presented as something that was said.** The guard against that has existed
  since the transcription was built, and it gave up above forty words — so the one case it
  is for, the model returning the *whole* prompt, was the case it let through. Found in the
  browser: a three-second recording in a day's thread read as a list of lifts and foods.
  The length of what comes back says nothing about whether it is speech, so the cap is gone;
  and because a prompt echoed alongside a few real words dilutes the ratio below any
  threshold, twelve of the prompt's words in the prompt's own order now count as an echo on
  their own. A long genuine note that names known foods is still a note.
- Six recordings of a capture with nine parts had no transcript at all: the capture was
  processed before 1.3.0 taught the transcription to read every part, and nothing went back
  for the ones it had skipped. They have been transcribed, and the transcripts that were the
  prompt rather than speech were blanked by the corrected rule.

## [1.5.0] - 2026-09-10

### Added
- **A showcase: the app is now visible without installing it.** The README opened on a prose
  description and an ASCII diagram, so the only way to find out what Victus looks like was to
  deploy it. [`docs/SHOWCASE.md`](docs/SHOWCASE.md) walks through the day with its bands and its
  thread, the catalogue, a product page with its density and its portions, the check-up and the
  body block — plus two short recordings: logging an item through a portion, and the question the
  app asks once when a unit has no portion yet. Three of them lead the README.
- `scripts/demo_seed.py` fills a throwaway tenant with a month of invented days, weights, body
  measurements and 17 products, which is what makes the pictures retakeable: when the interface
  moves on, the set is reshot from the same seed instead of being left to rot. Nothing in it is
  real, and no photograph or voice note of a person is used (SPEC R48).
  [`docs/media/README.md`](docs/media/README.md) records the seed, the one thing that has to be
  done by hand — signing in without a passkey — and the encoding the recordings are committed at.

### Changed
- The versioning rules say where documentation sits: a document that did not exist is an
  addition, one that said something wrong is a fix, and reshooting the pictures because the
  interface moved on is a fix rather than a feature.

## [1.4.0] - 2026-09-10

### Added
- **A density is a field of the product, not a secret of the API.** Since 1.2.0 a density
  actually converts an amount in the other unit before it is frozen, but `density_g_per_ml` was
  returned by nothing: missing from the product view, it reached neither the REST response nor a
  single MCP tool. It could be written and read nowhere, which left the one way out of R75 open
  only to whoever held a REST client. The product page now prints it with its unit and what it
  converts — beside the reference amount, not among the six nutrients, because it is not a value
  of the food — and says so when there is none, which is why grams of a syrup stated per
  millilitre get refused. The editor has the field. And the refusal that named it, *"set a
  density to allow g"*, names it in the problem's `errors` as well as in the sentence, so the
  portion form answers with an offer that opens the editor on that field instead of a sentence
  about a field the reader cannot find. The agent, which reads products only over MCP, can
  finally tell a product whose grams-to-millilitres conversion is safe from one whose is not.
- A pending portion proposal shows what each of its lines would do, and says when a line cannot
  be approved. The plan has been computed since 1.2.0 and rendered nowhere, so such a proposal
  appeared as one row holding a raw list of objects, with an approve button and no reason.

### Fixed
- **A portion proposal naming a `unit_code` that is not a unit read as ready to approve and then
  failed on the click.** Four arrived as `piece_s`, `piece_m`, `piece_l` and `piece_xl` — the
  sizes of an egg written where the unit belongs — and each was listed for review with nothing
  marked wrong. A proposal's plan now names every refusal the portion operations can raise, not
  only the two the database produces: a unit that does not exist (pointing at the closest one
  that does, and saying that a size belongs in the label), an amount that is not a positive
  number, an amount unit the product's reference values do not allow without a density, a
  `portion_id` that has been removed or belongs to another product, and an entry in a shape no
  operation accepts. The unit is read against the reference values the proposal *will* have
  applied, so moving a product to millilitres and adding a millilitre portion in one proposal is
  no longer half-refused, and a proposed new product's portions are read against its own values
  rather than a default of 100 g. And approving such a proposal is refused before anything is
  written: it used to mark the proposal approved, apply the product's other fields, and only then
  fail on the portion — a decision half applied.

### Changed
- `scripts/demo_seed.py` fills a tenant with invented food, weights and body measurements, so the
  app can be shown without showing anyone (R48). Every picture under `docs/media/` comes from it,
  which is what makes them retakeable when the interface changes instead of left to rot.

## [1.3.0] - 2026-09-10

### Added
- **"The recipe changed on this date" is something an actor can draft.** A new product version
  required `approve`, which was right about the decision and wrong about the drafting: an actor
  reading a changed label could only propose a correction to the *current* version, and that
  silently rewrites what every day before the change already counted. A proposal now takes a third
  kind, `version`, carrying `valid_from` beside the new values; approving it runs the same
  `NewProductVersion` a person would, so the version it revises keeps its numbers, its days and its
  portions. `product_version_create` degrades to that proposal without `approve`, exactly as the
  portion tools do, and takes an optional rationale — without the scope it is the only thing the
  person deciding gets to read. With this the drafting surface finally matches the deciding one for
  the whole catalogue, which is what ADR 0013 asks for; the gap in between was being filled by
  handing out `approve`. The review list says which promise it is looking at, because approving a
  version and approving a correction are opposite ones, and states the day above the values instead
  of listing it among them.
  Migration `0012` widens `ck_product_proposal_kind` to include `version`. SQLite cannot alter a
  CHECK, so the table is rebuilt from a spelled-out definition rather than from reflection:
  reflection recovers a CHECK by parsing the stored `CREATE TABLE`, and the day that stops matching
  it would drop `ck_product_proposal_status` without a word. Every step reads what is there first —
  a database created at this revision already has the wide constraint, because revision 0001 builds
  the schema from the models, and a SQLite database older than revision 0010 has the `kind` column
  with no constraint at all.
- A message in a day's thread carries its recordings, so the length of each shows there as it
  already did in the inbox. The thread had only the texts joined together, which is the right field
  to read for what was said and has nothing to say about how long it took.

### Fixed
- Deciding a proposal field by field would have dropped `valid_from` from a version proposal, because
  the filter kept only the fields named — and the day a version starts on is not a value under
  review. Picking values in the app would have answered with a validation error.

## [1.2.1] - 2026-09-10

### Fixed
- The length of a recording is measured instead of hoped for, so a card stops saying 0:00. Only
  the `whisper-*` models answer in verbose JSON and report a duration; the `gpt-4o` transcribers
  return the text alone, so the field was always null for the configured model — and with it the
  cost, which is derived from it. Loading the player's metadata cannot stand in either: a recording
  the browser's MediaRecorder produced carries no duration in its header, which is why the control
  read 0:00 until the file had played to the end and why `Duration:` in ffmpeg's own banner says
  `N/A` for exactly these files. The length now comes from decoding the audio and discarding the
  output, which is the one way to read a header that does not have it, and a failure to measure
  costs a label rather than the transcript.

## [1.2.0] - 2026-09-10

### Added
- **A day says what it was, in two or three sentences.** The numbers on a day answer "did I stay
  in the band"; nobody answered "was this a good day", which is the question a person opens a day
  with. The agent now writes one verdict per day, shown as a quiet block above the meals: what the
  day was, what was eaten as a shape rather than the table already on the page, and at most one
  small thing for tomorrow — and nothing at all when there is nothing to say. A later run replaces
  that verdict instead of stacking a second opinion under the first. The reasoning, the trends and
  the real advice stay in the report, where they can be that long. `agent_message_add` writes it
  without creating a draft, and `GET /days/{date}` carries it as `verdict`.
- **Editing a logged item is a form again**, in the same shape as adding one: the amount, the units
  the product actually supports — its measured family, its own portions, and a count unit whose size
  it asks for once — and the two estimate marks as checkboxes, **in both directions**. Withdrawing an
  estimate had been implemented on the server since the beginning and was unreachable from the page:
  an item marked ⚠️ because the agent guessed kept the mark for ever, even after the label had been
  read and the food weighed, and the mark feeds the estimate count, so a day read as less certain
  than it was. Editing used to be a browser prompt asking for one number. The same panel corrects an
  item on the draft approval page, where "the agent guessed, I know better" happens most.
- **A proposal can correct a portion and remove one, not only add one.** `changes.portions` carries an
  operation per entry — `add`, `update` or `delete` with its `portion_id` and a reason — and approving
  sends each to the use case it names; an entry without an operation still adds, which is how every
  proposal filed before this is stored. Cleaning up the catalogue earlier today took 18 portions
  removed and 8 corrected, and none of it could be proposed: it was done with a short-lived token
  holding `approve`, stepping around the review gate for exactly the kind of change the gate exists
  for (ADR 0013, R81). A pending proposal now also says what each line would do to the catalogue as
  it stands — the row it changes, how many logged items use it, and what would refuse it — so the two
  refusals the database produces, a twin under the unique `(product, unit, label)` and the `RESTRICT`
  on a portion days already point at, are visible before the approval instead of failing halfway
  through it. `portion_update` and `portion_delete` take the same road as `portion_create`: with
  `approve` they write, without it they propose.
- **Proposals are decided where they are listed.** A correction reads `carbs 42 → 8 g` instead of
  naming the field, with the product's other five numbers, its brand and how many line items already
  use it beside it, and with Approve, Reject and a link to that one proposal on the product page. A
  new product the agent met shows the same block plus its portions, and links to the day and meal its
  one-off was already eaten in — there is no page for an ad-hoc consumable, and the day it was eaten
  on is the better evidence anyway. `GET /products/{id}/usage` and the `product_usage` tool return
  `item_count`, and the id may be that one-off, which is how the proposal shows its day.
- `GET /api/v1/products` takes an `offset`, and the products page pages through the catalogue. The
  heading promised "All products (A–Z)" while the request asked for 25 rows, so every name past the
  twenty-fifth could only be reached by searching for a product you would first have to be able to
  name, and a catalogue above the endpoint's cap of 200 could not be listed in full at all. The page
  loads 50 at a time, says how many are shown, and offers the rest until a page comes back short.

### Fixed
- **A short name could not be found by typing it.** `Ei` is a word and also a syllable — it sits
  inside Weizen, Reis, Fleisch and Bäckerei, and 141 of 407 products contained it — and the hits came
  back in alphabetical order, so the product actually called "Ei" stood at position 39, past every
  result window, with all twenty rows above it false positives. The ranked matcher that would have
  known better only ran when the substring search came back nearly empty, so the more hits a query
  had, the worse its answer. Hits are now ordered by how well the name fits: the name itself, then a
  name that begins with the query, then a name whose later word does, then a syllable anywhere, a
  brand-only hit after those, alphabetical inside each tier. The fuzzy matcher contributes to every
  query, which is also what finds `Öl` — the query is folded to ASCII and the stored name is not, so
  a substring search never matched it at all.
- **A portion or an amount given in the other unit of measure was counted as if the units had
  matched**, so 400 ml of a syrup weighed in as 400 g and a tenth of its calories vanished. The
  density a product must carry for such a portion to be allowed is now actually applied: the amount
  is converted into the product's own unit before it is frozen — on a day, in an agent's draft, and
  in a recipe ingredient before a batch's totals are stored, where it mattered most because those
  totals are frozen and can never be recomputed. Days already logged keep the amounts frozen on them.
- **A capture with two spoken notes only ever had the first one transcribed.** The second was stored,
  it played back, and nothing ever read it: the request went to whichever audio file came first, and
  the schema had room for exactly one transcript per capture, so there was nowhere to put a second
  text. The card then printed that one text once underneath both players, which told the reader
  neither which recording it belonged to nor that the other had never been listened to. Every
  recording is now transcribed and carries its own text under its own player; one still waiting says
  so on its own line instead of borrowing its neighbour's. The day's thread and the day context the
  drafting prompt is built on carry every note too — that was the one place where a dropped sentence
  turned into a missing meal.
- **Every recording showed a length of 0:00.** The player was told to preload nothing, so the browser
  had no metadata to take a duration from, and pressing play was the only way to find out how long a
  note was. The player now loads the metadata, and the length the transcription provider measured is
  kept with the recording and printed beside it — `0:42 · "…"` — so a capture in the inbox can be
  judged without playing it.
- `GET /api/v1/proposals` answered 500 for any proposal about a portion. Its `current` block filled
  itself from the product's fields and `portions` is a relationship, so the response carried database
  rows that cannot be serialised — that is every proposal a portion suggestion files without
  `approve`, the road ADR 0013 sends an agent down.
- A proposal's timestamp on the product page was cut out of the stored ISO string, so it read UTC:
  the wrong hour, and after midnight the wrong day.
- **Four patterns that read text a person supplies could be made to cost a full scan per character
  position.** Three pull labels out of `[[wikilinks]]` and `[Label](links)` in a quantity, one strips
  a parenthesised part off a name before matching, and all of them are reached by whatever a person
  or a transcript writes. A pasted run of `[[` cost seconds of CPU per call at 60 000 characters; the
  character classes now stop at the next bracket, so the same input costs a millisecond, and every
  label, escaped pipe and parenthesised short form still comes out as before.
- The translation check read string literals with a pattern that, on a quote nobody closed,
  backtracked over everything behind it — exponentially, over our own source. It now scans a literal
  the way the argument reader beside it always did: to the first unescaped closing quote, and no
  further than the line. An unclosed quote yields no key instead of one guessed out of the characters
  behind it, and every dictionary still reads with the same entries.
- **The published api image carried seven util-linux advisories, a setuptools path traversal and an
  msgpack out-of-bounds read, and none of them were ours.** The seven came in with `libuuid`, a shared
  library of the runtime package list that Alpine had already patched inside the pinned release; the
  other two came with the interpreter's own pip and setuptools, which nothing in this image ever runs,
  because everything executes from the copied virtualenv. The build now takes the distro's patches
  before adding its own packages and deletes pip and setuptools from the runtime interpreter. A
  container that mounts nothing never had the util-linux tools to begin with.
- The caddy image declares a `HEALTHCHECK` against caddy's admin endpoint — the same probe the compose
  service uses — so a caddy that is up but not serving is visible to anything that waits for health.

### Changed
- The item table a run drafts is no longer filed in the day's thread as that day's `summary`. It is
  the run's page and stays in the run summary, where it is read; `summary` is now the day's verdict
  above the meals, and the thread keeps the notes and the questions. Left as it was, it would have
  overwritten every verdict, because it is written after the session that produces one.
- `deploy/Dockerfile.api` writes its base image tag into both stages instead of holding it in an
  `ARG`: Dependabot cannot resolve `FROM ${ARG}` and was watching the web and caddy images but not
  this one. Dependabot alerts, Dependabot security updates and private vulnerability reporting are
  now enabled on the repository, so the next such advisory arrives as a pull request instead of
  sitting in a list.
- R75 is written down in the specification. It was referenced from two places in the code and the
  requirement table went straight from R74 to R76 — the rule existed only as a comment.

## [1.1.0] - 2026-09-10

### Added
- A logged item names the portion it was resolved through, not only its unit. One unit can hold
  several portions — an egg is `piece` in the four German trade classes, 43 to 65 g — and the day
  table read "1 Stück" for all of them, a difference of 34 kcal the page could not show. The item
  now carries `portion_id` and `portion_label`, the day table and the Markdown export print
  `2 Stück (L)`, and a label that only repeats the unit's own word is left off, because
  "1 Stück (Stück)" says nothing and is what every portion created before labels looks like.

### Fixed
- A day nobody classified had no target band, so it showed no gauges and every macro of it
  went unrated in the reports. There are three kinds of day — rest, strength, martial arts —
  and the day form offered a fourth option, labelled "none / rest", whose value was no type
  at all. Until the generic band expired such a day was still covered; from the day the three
  typed bands replaced it, nothing matched. It was the default option, so it happened by not
  choosing. The rule the label already promised is now the rule: **no training is rest.** A
  band for any day still wins over the rest band for such a day, and a type that was actually
  asked for is never traded for another — a martial arts day with no martial arts band still
  answers "no band" rather than quietly measuring itself against a resting standard. A new day
  starts as a rest day, and the form offers the three kinds and no empty fourth.

### Changed
- The test plan carries the rule that automated levels cannot cover: **every area a change
  touched, and every area downstream of it, is opened in a browser and looked at before the
  change is done.** Every fault that reached a reader — a timestamp in the wrong zone, an
  English sentence on a German page, a recording showing 0:00, a day without a band — passed a
  green suite and was obvious on the page.
- `CONTRIBUTING.md` states the versioning rules: which surfaces the version covers, which part
  a change raises, and the ordered list a release goes through. A default that changes is a fix
  as long as the old value stays accepted; when in doubt, take the higher part.

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
