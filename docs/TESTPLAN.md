# Test plan

Every test case has an ID, a level, and a fixture. Automated cases live under `tests/` (Python) and `web/` (Angular,
Playwright); manual cases are checklists per stage. This document is the source of truth for *what* is tested;
the code is the source of truth for *how*.

## Strategy

| Level | Scope | Runner | Data | Speed |
|---|---|---|---|---|
| **Domain** (`T-DOM`) | Pure functions: nutrition, TDEE, trend, forecast, burndown, band rating, consistency, matching, quantity parser | pytest, no DB | fixtures in `tests/fixtures/` | ms |
| **Importer** (`T-IMP`) | Markdown parsers, matching driver, round-trip gate | pytest, in-memory SQLite | anonymised sample logs in `tests/fixtures/vault_sample/` | ms–s |
| **Service** (`T-SVC`) | Use cases with in-memory SQLite (FK pragma on), in-memory ports | pytest | factories | s |
| **API** (`T-API`) | FastAPI `TestClient`, two tenants, session and token auth | pytest | factories | s |
| **Agent** (`T-AGT`) | Tool registry, runner and worker with a scripted model client (no network) | pytest, in-memory SQLite | scripted model | s |
| **MCP** (`T-MCP`) | MCP server over the in-memory transport and `/mcp` over HTTP (auth, CIDR, rate limit) | pytest | client | s |
| **Web** (`T-WEB`) | Angular unit tests (Vitest), component and service tests | `npm test` | mocked API | s |
| **E2E** (`T-E2E`) | Playwright against `docker compose --profile dev`, virtual authenticator | `npx playwright test` | seeded tenant `alice` | min |
| **Migration** (`T-MIG`) | Full vault import on the sample vault, gate and report | pytest, file SQLite | `tests/fixtures/vault_sample/` | s |
| **Operations** (`T-OPS`) | Backup/restore, health, Compose smoke | pytest + shell | temp dirs | s–min |

The pyramid is deliberate: most cases are `T-DOM`/`T-SVC`; E2E covers the two flows a user cannot live without
(login, approving a draft).

## Conventions

| Item | Rule |
|---|---|
| ID | `T-<LEVEL>-<3 digits>`, stable; retired cases are marked *retired*, never renumbered |
| pytest marker | `@pytest.mark.<level>` (`domain`, `importer`, `service`, `api`, `agent`, `mcp`, `migration`, `ops`) |
| DB matrix | `--db sqlite` (default) and `--db postgres` (service container in CI) for `T-SVC`, `T-API`, `T-MIG` |
| Fixtures | Synthetic or anonymised; no real personal or health data (SPEC R48) |
| Tolerances | kcal ±1, macros ±0.1 g, salt ±0.01 g, weight ±0.01 kg, TDEE ±1 kcal unless stated |

## Domain (`T-DOM`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-DOM-001 | Macros for a line item | product per 100 g, base quantity | `nutrition.macros_for(item, per100)` | `kcal = per100.kcal × base_quantity / 100` etc. | inline | yes | 1 |
| T-DOM-002 | Pure function equals SQL view | 20 seeded items | compare `macros_for` with `line_item_macros` | identical within tolerance for every row | `service` DB | yes | 1 |
| T-DOM-003 | Weekly TDEE (predecessor formula) | daily weights and kcal | `tdee.weekly_tdee(daily, kcal, kcal_per_kg)` | per ISO week `raw = avg_kcal + (−Δkg × kcal_per_kg) / days_with_kcal`, smoothed `(raw + prev) / 2`, out of 1000–6000 → `None` | `tdee_reference.json` | yes | 2 |
| T-DOM-004 | Rolling TDEE windows 3/7/14/21/30/60/90 | same | `tdee.rolling_tdee(...)` | equals reference per window ±1 kcal; divisor = calendar days; Δ from the 7-day MA | `tdee_reference.json` | yes | 2 |
| T-DOM-005 | Rolling TDEE grade | window results | `reliability.grade(days, coverage, days_without_macros)` | red if days < 7 or coverage < 50 %; yellow if days < 14 or coverage < 70 % or ≥ 2 days without macros; else green | inline | yes | 2 |
| T-DOM-006 | Moving average | 30 daily values with gaps | `trend.moving_average(series, 7)` | backward window over calendar days, gaps ignored, equals reference | `tdee_reference.json` | yes | 2 |
| T-DOM-007 | Regression trend per window | MA series | `trend.trend_windows(ma, daily, [7,14,21,30,60,90])` | slope kg/day equals reference ±0.0005 | `tdee_reference.json` | yes | 2 |
| T-DOM-008 | Forecast horizons and ETA | trend, current MA, goal | `forecast.forecast(...)` | 1/3/6-month projections and weight at goal date ±0.01 kg; ETA `None` when slope ≥ −0.001 | `tdee_reference.json` | yes | 2 |
| T-DOM-009 | Burndown planned vs. actual | goal, stages, MA series | `burndown.burndown(...)` | planned path linear to each stage; gap and required rate equal reference ±0.01 | `tdee_reference.json` | yes | 2 |
| T-DOM-010 | Yearly stats | multi-year weights | `trend.yearly_stats` | start/end/delta/min/max/avg per year | inline | yes | 2 |
| T-DOM-011 | Band distribution | 14 days macros, target band | `band_rating.distribution(values, band)` | counts below min / between / optimal / above max sum to n; average correct | inline | yes | 2 |
| T-DOM-012 | Asymmetric corridor | kcal series, corridor 1400–2000 asymmetric | rating | below min is not a finding; above max is; average rating uses countable days only | inline | yes | 2 |
| T-DOM-013 | Consistency type 0 — missing flags | day without `reliable` or `status` | `consistency.check_day` | finding type 0, blocks countability | inline | yes | 1 |
| T-DOM-014 | Consistency type 1 — source vs. computed drift | `source_kcal` differs by > 3 % | check | finding type 1 with both values | inline | yes | 1 |
| T-DOM-015 | Consistency type 2 — meal totals vs. items | meal total row off by 10 kcal | check | finding type 2 | inline | yes | 1 |
| T-DOM-016 | Consistency "not assessable" | meal table without total row | check | result *not assessable*, **not** an error | inline | yes | 1 |
| T-DOM-017 | Consistency type 3 — gaps | countable day lacking fiber | check | type 3 finding; salt-only gaps flagged as *expected* before salt tracking start | inline | yes | 1 |
| T-DOM-018 | Quantity parser golden | 40 strings (`346 g`, `0,5 l (1 Flasche)`, `~240 g ⚠️`, `500 g (ganzer Becher)`, `3 Stück`, `½ Dose`, `2 × 300 ml`, `53 g (~2,1 Scoops)`) | `quantity_parser.parse` | value, unit code, estimated flag, portion hint as in golden file | `quantity_golden.yaml` | yes | 1 |
| T-DOM-019 | Number normalisation | `1.056`, `150,5`, `2.568,25`, `12` | `parse_number` | 1056, 150.5, 2568.25, 12 | inline | yes | 1 |
| T-DOM-020 | Matcher stage 1 | index with "Potato (raw)" and "Potato (cooked)" | `ProductIndex.find("Potato (raw)")` | stage 1, score 1.0, correct id — parentheses are significant | inline | yes | 1 |
| T-DOM-021 | Matcher stage 2 uniqueness | short form ambiguous | `find("Potato")` | **no** stage-2 hit; falls through to fuzzy with both candidates | inline | yes | 1 |
| T-DOM-022 | Matcher substring trap | ingredient "flaxseed (ground)" and recipe "skyr berry flaxseed bowl" | `find("flaxseed (ground)")` | matches the product, not the recipe | inline | yes | 1 |
| T-DOM-023 | Matcher threshold | coverage 0.61 vs 0.62 | `find` | 0.61 → no match, 0.62 → stage 3 | inline | yes | 1 |
| T-DOM-024 | Target band for a date and training type | three versions | `target_band.for_date(bands, date, training_type)` | picks the version valid at date; falls back to `rest` when type unknown | inline | yes | 1 |
| T-DOM-025 | Frozen quantities, propagating nutrients | item with base_quantity; product kcal changed | recompute | base_quantity unchanged, kcal changed | inline | yes | 1 |
| T-DOM-026 | Implied TDEE and required rate (status arithmetic) | window weights and kcal; goal | `tdee.implied_tdee`, `tdee.required_rate`, `tdee.eat_target` | `mean_kcal + (−Δkg × kcal_per_kg) / n_kcal`; rate = (goal − current)/days × 7; deficit = −slope × kcal_per_kg; eat = tdee_ref − deficit | inline | yes | 2 |
| T-DOM-027 | Training type from free text | German/English training notes | `target_band.training_type_from_text` | "krafttraining (5x5)" → strength, "kickboxing" → martial_arts, "nein (Sauna)" → rest, unknown → `None` | inline | yes | 1 |
| T-DOM-028 | Multiplication anywhere in a quantity | `2 Fl. à 0,5 l`, `2 Flaschen (2 × 0,33 l)` | `parse_quantity_details` | base amount = count × per-piece volume (1000 ml / 660 ml) | inline | yes | 1 |

## Importer (`T-IMP`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-IMP-001 | Frontmatter macros | log with macro block | `parse_day_log` | six macros read as floats; decimal point | `vault_sample/days/…/frontmatter.md` | yes | 1 |
| T-IMP-002 | Balance-section fallback | log without frontmatter macros, bold and non-bold rows | parse | values read from the balance table regardless of bold | `…/legacy_balance.md` | yes | 1 |
| T-IMP-003 | Late meal after the balance section | meal heading after balance | parse | meal included in items and totals | `…/late_meal.md` | yes | 1 |
| T-IMP-004 | Escaped pipes in wikilinks | `[[x\|Name]]` in cells | split cells | 8 cells, name = display text | `…/wikilinks.md` | yes | 1 |
| T-IMP-005 | 7- vs 8-column tables | both variants | parse | salt `None` for 7 columns, value for 8 | `…/seven_cols.md`, `…/eight_cols.md` | yes | 1 |
| T-IMP-006 | Planning sections ignored | headings "Vorschlag", "Restbedarf" | parse | rows under planning headings not counted; "Essensplan" in a meal heading **is** counted | `…/planning.md` | yes | 1 |
| T-IMP-007 | Flags without defaults | log missing `offen` | parse | `status = None`, reported as type-0 finding, not silently `open` | `…/no_flags.md` | yes | 1 |
| T-IMP-008 | Food table parsing | sample foods file | `parse_products` | products, categories from headings, salt and portions from free text, `verified` from ✓/label marker, EAN regex | `vault_sample/foods.md` | yes | 1 |
| T-IMP-009 | Recipe parsing | sample recipe | `parse_recipe` | name, servings, ingredients, per-100 nutrients | `vault_sample/recipes/*.md` | yes | 1 |
| T-IMP-010 | Weight CSV | `timestamp;weight_kg`, duplicates | import | rows unique per timestamp; out-of-range (< 30, > 400) rejected with report line | `vault_sample/weight/raw.csv` | yes | 1 |
| T-IMP-011 | Idempotent re-run | import twice | counts | second run writes 0 new rows | sample vault | yes | 1 |
| T-IMP-012 | `--replace-day` | day modified in source | re-import one day | only that day's meals/items replaced; products untouched | sample vault | yes | 1 |
| T-IMP-013 | Review list content | unmatched items | report | each with top-3 candidates and scores, day, raw text | sample vault | yes | 1 |

## Service (`T-SVC`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-SVC-001 | FK pragma on | fresh SQLite engine | `PRAGMA foreign_keys` | returns 1 on every pooled connection | – | yes | 1 |
| T-SVC-002 | Subtype FK safety | insert `line_item` pointing at a batch id with kind `product` | commit | integrity error | factories | yes | 1 |
| T-SVC-003 | One default portion | second default portion for same product+unit | commit | unique violation | factories | yes | 1 |
| T-SVC-004 | Cook a batch freezes totals | recipe with ingredients | `CookBatch`; then change an ingredient product | batch totals unchanged | factories | yes | 1 |
| T-SVC-005 | Close day freezes target band | day open, two band versions | `CloseDay` then add a newer band | `day.target_band_id` unchanged | factories | yes | 1 |
| T-SVC-006 | Countable view | days with all combinations of `reliable` × `status` | query `countable_days` | only `reliable=1 AND status='closed'` | factories | yes | 1 |
| T-SVC-007 | Manual weight only | `AddWeight(source='scale_sync')` via API use case | execute | rejected; `manual` accepted; delete of non-manual rejected | factories | yes | 1 |
| T-SVC-008 | ReassignLineItem | ad-hoc item, product | execute | `consumable_id` changed, `base_quantity` unchanged, macros now from product | factories | yes | 1 |
| T-SVC-009 | Capture idempotency | same bytes uploaded twice | `CreateCapture` | second call returns existing id, no new row | factories | yes | 3 |
| T-SVC-010 | Agent lock acquire/conflict | run A holds lock for date | run B `StartAgentRun` same date | B skips the day; `draft_create` by B raises `LockHeldByOtherRun` | factories | yes | 3 |
| T-SVC-011 | Lock expiry | lock with `locked_until` in the past (TTL default 5 min) | run B starts | B acquires the lock | factories | yes | 3 |
| T-SVC-012 | CreateDraft | run with lock, transcript | execute | `day_log.status='draft'` or `is_draft=1` items; confidence, reasoning, alternatives stored; captures → `assigned` | factories | yes | 3 |
| T-SVC-013 | ApproveDay | draft day with 3 items, correction for one | execute with `close=true` | `is_draft=0`, corrected quantity, `estimated` preserved, `status='closed'`, `target_band_id` set, captures `processed`, 1 audit row per change | factories | yes | 3 |
| T-SVC-014 | ApproveDay keeps day open | as above, `close=false` | execute | `status='open'`, band not frozen | factories | yes | 3 |
| T-SVC-015 | Budget stop | budget 1000 tokens, usage 1200 | worker loop | run ends `budget_exceeded`, locks kept until expiry, summary written | fake LLM | yes | 3 |
| T-SVC-016 | Tenant scoping in repositories | two tenants with same product name | `products.search` as tenant A | only A's rows | factories | yes | 1 |
| T-SVC-017 | Settings versioning | two `PUT /settings` | read for date between versions | version valid at that date | factories | yes | 1 |
| T-SVC-018 | Salt only in target bands | settings JSON containing `salt` key | validate | schema error | inline | yes | 1 |
| T-SVC-019 | One session per day | batch run over 3 days with captures | worker loop with recording fake LLM | 3 sessions opened; session for day N receives only day N's captures/transcripts; no message from another day present | fake LLM | yes | 3 |
| T-SVC-020 | Day assignment precedes drafting | captures without `target_date` | run | classification step sets `target_date` before any drafting session starts; drafting session prompts contain no unassigned capture | fake LLM | yes | 3 |
| T-SVC-021 | `captures_open` scoped to locked day (MCP) | run holds lock for day A; open captures for A and B | `captures_open(run_id)` | only day A's captures returned | factories | yes | 3 |
| T-SVC-022 | Follow-up after draft | day with pending draft; new text message | `AddDayMessage` | `follow_up` run queued for that day only; session input contains current draft + thread + new message | fake LLM | yes | 3 |
| T-SVC-023 | Message during a locked run | day locked by run A; message arrives | run A finishes | message still `new`; a `follow_up` run is queued automatically; no second draft of the same items | fake LLM | yes | 3 |
| T-SVC-024 | Agent question round-trip | draft with `open_questions` | run finishes; user replies via message | question stored as `day_message(kind=question)`; reply queues follow-up; draft updated incrementally | fake LLM | yes | 3 |
| T-SVC-030 | Capture dedupe | text capture uploaded | `UploadCapture` twice with the same text | second call returns the existing capture with `created=False`; one row | in-memory blobs | yes | 3 |
| T-SVC-031 | MIME sniffing | `.oga` upload with `application/octet-stream` | `UploadCapture` | kind `audio`, attachment `audio/ogg`; unsupported type → 422 | in-memory blobs | yes | 3 |
| T-SVC-032 | Follow-up queueing and merging | day with draft items | `AddDayMessage` twice | exactly one queued `follow_up` run for the day; the second message merges into it (`captures` list grows) | factories | yes | 3 |
| T-SVC-033 | Transcription stored | audio capture, fake `TranscriptionPort` | `TranscribeCapture` | `transcript` row with provider/model/text; second call without `force` returns the stored text | fake port | yes | 3 |
| T-SVC-034 | Transcription failure | fake port raising `TranscriptionError` | `TranscribeCapture` | capture `failed`, `ExternalServiceError` raised, audit row written | fake port | yes | 3 |
| T-SVC-035 | Run begin locks days | two new captures for two days | `QueueAgentRun` → `BeginAgentRun` | run `running`, both days locked, `days` sorted oldest first | factories | yes | 3 |
| T-SVC-036 | Lock conflict skipped | day locked by run A | `BeginAgentRun` for run B on the same day | day in `skipped_days` with the holder's id; run B still runs for its other days | factories | yes | 3 |
| T-SVC-037 | Draft schema validation | running run holding the lock | `CreateDraft` with a draft missing `confidence` | 422 with the failing path; nothing written | factories | yes | 3 |
| T-SVC-038 | Draft creation | valid draft (product item + ad-hoc item, notes, open question) | `CreateDraft` | `day_log` status `draft`, items `is_draft=1` with confidence/rationale/alternatives, `ad_hoc_item` created, captures `assigned`, note + question in the thread | factories | yes | 3 |
| T-SVC-039 | Draft needs the lock | run B without the day's lock | `CreateDraft` | `LockHeldByOtherRun`; nothing written | factories | yes | 3 |
| T-SVC-040 | Finish releases locks | running run with locks | `FinishAgentRun` | status final, `finished_at` set, zero locks left; finishing again is a no-op | factories | yes | 3 |
| T-SVC-041 | Session roll-up | run with two `RecordAgentSession` calls | read run | run tokens and cost equal the sum of the sessions | factories | yes | 3 |
| T-SVC-042 | Approval processes captures | drafted day with assigned captures | `ApproveDay` | captures `processed`, `processed_at` set, items no longer draft | factories | yes | 3 |
| T-SVC-043 | Cancel run | queued and running runs | `CancelAgentRun` | status `cancelled`, locks released; cancelling a finished run → 409 | factories | yes | 3 |

## Reports (`T-RPT`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-RPT-001 | Definition parsing | valid YAML with every block type | `load_definition` | typed blocks, defaults applied (period 14d, horizons, columns) | inline | yes | 2 |
| T-RPT-002 | Definition rejects unknown block / bad ids | YAML with `type: pie` or `id: "Bad Id"` | `load_definition` | `ValidationError` | inline | yes | 2 |
| T-RPT-003 | Built-in `checkup.yaml` is schema-valid | packaged YAML | validate against `schemas/report-definition.schema.json` | valid; registry lists `checkup` as built-in and tenant reports cannot shadow it | package | yes | 2 |
| T-RPT-004 | `tdee_windows` equals frozen reference | synthetic fixture as data source | render block for windows 3…90 | mean kcal, Δ, TDEE, coverage, quality identical to `tdee_reference.json` | `tdee_reference.json` | yes | 2 |
| T-RPT-005 | `trend` / `forecast` equal frozen reference | as above | render | slopes, rates, m1/m3/m6, ETA identical | `tdee_reference.json` | yes | 2 |
| T-RPT-006 | `burndown` equals frozen reference | as above, stages from settings | render | anchor, remaining, gap, per-stage rates identical | `tdee_reference.json` | yes | 2 |
| T-RPT-007 | `band_distribution` sums | protein series and band | render | zone counts sum to `n`; `below_optimum + above_optimum` equals the reference "between"; kcal rated against the asymmetric corridor | `tdee_reference.json` | yes | 2 |
| T-RPT-008 | `kpi_tile` metric paths | every path in `metrics.PROVIDERS` | render | value or `None` with note; unknown path → `BlockError`, other blocks still render | in-memory | yes | 2 |
| T-RPT-009 | `day_list` limit and columns | 30 days, one open day | `limit: 5`, columns incl. weight/status | 5 newest rows, weight joined, open day flagged not countable | in-memory | yes | 2 |
| T-RPT-010 | `text_finding` empty and filled | no finding / agent finding with 8 bullets, `max_items: 5` | render | `None` → placeholder text / first 5 bullets kept | in-memory | yes | 2 |
| T-RPT-011 | Missing weight data | source without weights | render checkup | weight-based blocks are `BlockError`, `day_list` and `text_finding` render, weight tile is `None` | in-memory | yes | 2 |
| T-RPT-012 | Markdown renderer | rendered checkup | `to_markdown` | headings per block, table headers, traffic-light emoji only here, English number format, errors shown with ⚠️ | in-memory | yes | 2 |
| T-RPT-013 | JSON renderer round-trip | rendered checkup | `to_dict` → `json.dumps` | serialisable; dates ISO; enums as values; `error` flag per block | in-memory | yes | 2 |
| T-RPT-014 | Countable days only | one non-countable day with absurd kcal | render `kcal.average` | only `reliable` + `closed` days contribute | in-memory | yes | 2 |
| T-RPT-015 | Historical render | `today` 60 days in the past | render `weight.latest` | period ends on that day; no weigh-in after it is used | in-memory | yes | 2 |

## API (`T-API`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-API-001 | Passkey registration | invitation session, virtual authenticator (`soft-webauthn`) | options → verify | credential stored, `sign_count` 0 | client | yes | 1 |
| T-API-002 | Passkey login | registered credential | options → verify | session cookie set, `HttpOnly; Secure; SameSite=Lax` | client | yes | 1 |
| T-API-003 | Replay / sign-count regression | assertion with lower `sign_count` | verify | 401, credential flagged | client | yes | 1 |
| T-API-004 | CSRF on writes | session without `X-CSRF-Token` | `POST /days/2026-09-01/meals` | 403 | client | yes | 1 |
| T-API-005 | RP_ID pin | first passkey registered with `rp_id=a` | restart app with `rp_id=b` | startup fails with `RP_ID mismatch` | client | yes | 1 |
| T-API-006 | Recovery code | valid code | `POST /auth/recovery` | 15-minute session; only `/auth/passkeys` and `/auth/me` allowed | client | yes | 1 |
| T-API-007 | Token creation and single display | `POST /auth/tokens` | response | secret present once; `GET` shows prefix only | client | yes | 1 |
| T-API-008 | Token scopes | token `read` | `POST /products` | 403; `GET /products` 200 | client | yes | 1 |
| T-API-009 | Token expiry | expired token | any call | 401 | client | yes | 1 |
| T-API-010 | Token revocation | revoked token | any call | 401 immediately | client | yes | 1 |
| T-API-011 | Foreign tenant → 404 (parametrised over every router) | tenant B resource id | GET/PATCH/DELETE as A | 404, no body leak | two tenants | yes | 1 |
| T-API-012 | Search endpoint | products seeded | `GET /products?q=` | ranked, includes `stage`, `score` | client | yes | 1 |
| T-API-013 | Day detail computes macros | day with items | `GET /days/{date}` | macros equal view; target band and findings present | client | yes | 1 |
| T-API-014 | Problem+json errors | invalid body | any POST | `application/problem+json`, field paths | client | yes | 1 |
| T-API-015 | Health | running app | `GET /health` | `db`, `storage`, `scheduler`, `backup_age_hours` | client | yes | 1 |
| T-API-016 | OpenAPI client drift | generated client committed | regenerate in CI | no diff | CI | yes | 1 |
| T-API-017 | Capture upload | multipart audio | `POST /captures` | 201, hash, transcript job queued; second upload → 200 existing | client | yes | 3 |
| T-API-018 | MCP HTTP auth | `/mcp` without token / with `read` token | tool call `day_approve` | 401 / 403 | client | yes | 3 |
| T-API-019 | MCP CIDR allow-list | request from outside `mcp.allowed_cidrs` | any `/mcp` call | 403 | client | yes | 3 |
| T-API-020 | Rate limit | > `rate_limit_per_minute` calls | `/mcp` | 429 | client | yes | 3 |
| T-API-021 | Capture list, detail, patch | two tenants, captures for A | `GET /captures`, `PATCH /captures/{id}` as A and as B | A sees and edits; B gets 404 on every capture route | client | yes | 3 |
| T-API-022 | Attachment download | image capture | `GET /attachments/{id}` | bytes identical, `Content-Type` of the upload, `Cache-Control: private`; other tenant 404 | client | yes | 3 |
| T-API-023 | Audio upload transcribes | fake transcription | `POST /captures` with an audio file | 201, `transcript` filled; with a failing provider the capture is `failed` and the upload still 201 | client | yes | 3 |
| T-API-024 | Agent run lifecycle | signed-in owner | `POST /agent/runs` → `GET /agent/runs/{id}` → `POST …/cancel` | 202 `queued`; detail with `sessions: []`; cancel → `cancelled`; other tenant 404 | client | yes | 3 |
| T-API-025 | Locks | running run | `GET /agent/locks`, `DELETE /agent/locks/{date}` | lock listed with `run_id`; delete removes it; `read`-only token → 403 on delete | client | yes | 3 |

## Web (`T-WEB`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-WEB-001 | Day view renders macros and band gauges | mocked `GET /days/{date}` (200 and 404) | render component | values, ⚠️ on estimated items, draft tint, gauge zones; 404 shows “Create this day” with mandatory reliable choice and posts `POST /days/{date}` | mock | yes | 1 |
| T-WEB-002 | Product search debounce | typing | 300 ms debounce, one request per pause | mock | yes | 1 |
| T-WEB-003 | Draft approval form | mocked drafts | edit quantity, approve | request body contains corrections and `close` | mock | yes | 3 |
| T-WEB-004 | Report dashboard blocks | mocked `ReportResult` | render | every block type has a component; unknown type shows a placeholder | mock | yes | 2 |
| T-WEB-005 | Passkey nudge | `passkeys.length < 2` | login | banner shown; hidden at 2 | mock | yes | 1 |
| T-WEB-006 | App shell | signed out / signed in (`AuthService.me`) | render `App` | bare layout when signed out; rail with 9 entries, tenant name and API version when signed in; unreachable API shows an error dot | mock | yes | 1 |
| T-WEB-007 | AuthService and interceptor | mocked `/auth/me`, WebAuthn options with `ceremony_id`, writes, 401 | load, login, register, recover, post, logout | 401 on `/auth/me` = signed out without redirect; options minus `ceremony_id` go to the browser, `ceremony_id` (and passkey `name`) echoed on verify; recovery login sets `recovery_session`; `X-CSRF-Token` on writes; 401 on protected route → `/login`; logout clears session even on 500 | mock | yes | 1 |
| T-WEB-008 | ApiClient contract | – | call each method group | paths, query params and bodies match `docs/API.md` (days, products, line items, reports, messages, agent runs) | mock | yes | 1 |
| T-WEB-030 | ApiClient capture/agent methods | – | call `updateCapture`, `transcribeCapture`, `captures(status,date)`, `attachmentUrl`, `agentRuns`, `cancelAgentRun`, `agentLocks`, `forceUnlock` | paths, methods, params and bodies match `docs/API.md` | mock | yes | 3 |
| T-WEB-031 | Agent page | mocked runs and locks | render; select a run; cancel; force unlock | runs with status/tokens/cost; detail with sessions and rendered summary; cancel posts `/cancel`; unlock only after inline confirmation, `DELETE /agent/locks/{date}` | mock | yes | 3 |
| T-WEB-032 | Captures page | mocked captures (audio with transcript, image) | render; set day; discard; duplicate upload | transcript and audio element, image thumbnail via `/attachments/{id}`; `PATCH` bodies; `created: false` shows a notice, no new row | mock | yes | 3 |
| T-WEB-033 | Day thread states | mocked messages with `processing_state` and agent kinds | render `DayThread` | user captures show "waiting for the agent" / "in draft"; agent messages tagged summary/question/note; composer enabled while a run is active | mock | partly (manual) | 3 |

## Agent (`T-AGT`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-AGT-001 | Registry schemas | – | build Anthropic tool definitions from `mcp/tools.py` | every tool has a name, description and a valid JSON schema; scopes assigned | inline | yes | 3 |
| T-AGT-002 | Dispatch and scopes | tool context with `read` only | dispatch `product_search`, then `draft_create` | first returns candidates; second rejected with a scope error before the use case runs | in-memory SQLite | yes | 3 |
| T-AGT-003 | Worker end to end | tenant, product with portion, text capture for a day, `ScriptedModelClient` (product_search → draft_create → end_turn) | `QueueAgentRun`, `Worker.run_once()` | `day_log` draft with `is_draft` items, one `agent_session` row, run `finished` with a summary containing the day header, capture `assigned`; afterwards `day_approve` → capture `processed` | scripted model | yes | 3 |
| T-AGT-004 | One session per day | captures for three days | `Worker.run_once()` | three `agent_session` rows; each session's messages contain only that day's captures | scripted model | yes | 3 |
| T-AGT-005 | Budget exceeded | `max_usd_per_run` below the first session's cost | run | run `budget_exceeded`, remaining days unlocked, summary explains | scripted model | yes | 3 |
| T-AGT-006 | Refusal | scripted `stop_reason=refusal` | run | session outcome `refused`, day not drafted, run `finished` with the note in the summary | scripted model | yes | 3 |
| T-AGT-007 | Stuck loop | model keeps calling `product_search` | run | session ends after `max_turns_per_day` with outcome `stuck`; lock released | scripted model | yes | 3 |
| T-AGT-008 | Missing API key | `providers.anthropic_api_key` unset | `Worker.run_once()` on a queued run | run `failed` with a clear error, no exception, locks released | – | yes | 3 |
| T-AGT-009 | Follow-up merge | drafted day, two new messages | `Worker.run_once()` | one `follow_up` run processed, the duplicate marked `cancelled` ("merged into …"), draft changed incrementally | scripted model | yes | 3 |
| T-AGT-010 | Cron tick | `agent.enabled`, `cron` matching the fake clock | worker tick | one `historical` run queued per active tenant; no run when `cron` is `null` | fake clock | yes | 3 |
| T-AGT-011 | Heartbeat | worker tick | inspect heartbeat path | file touched every tick (compose healthcheck contract) | temp dir | yes | 3 |
| T-AGT-012 | Prompt version | – | compute `prompt_version` | 12 hex digits; changes when a prompt file changes | inline | yes | 3 |

## MCP (`T-MCP`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-MCP-001 | Server builds | tool context | `build_server()` and list tools | every registry tool registered with its schema | in-memory | yes | 3 |
| T-MCP-002 | Tool call in-process | in-memory MCP client | call `day_get` | result equals the use case's output as JSON | in-memory | yes | 3 |
| T-MCP-003 | External run protocol | two clients | `agent_run_start` on both for the same day | second gets the day in `skipped_days`; `draft_create` from the second → `LockHeldByOtherRun` | in-memory | yes | 3 |
| T-MCP-004 | HTTP auth | `mcp.http_enabled`, no token / `read` token | `POST /mcp` | 401 / tool with `approve` scope → 403 | client | yes | 3 |
| T-MCP-005 | HTTP CIDR | client address outside `allowed_cidrs` | `POST /mcp` with a valid token | 403 | client | yes | 3 |
| T-MCP-006 | HTTP rate limit | more than `rate_limit_per_minute` calls | `POST /mcp` | 429 | client | yes | 3 |
| T-SVC-044 | Meal rename/time | day with meal | `UpdateMeal(name, time)` | meal renamed, time set | service | yes | 3 |
| T-SVC-045 | Meal delete guard | meal with one item | `DeleteMeal` | 409 Conflict; after deleting the item the meal is deleted | service | yes | 3 |
| T-SVC-046 | Meal tenant isolation | Alice's meal | Bob calls `UpdateMeal`/`DeleteMeal` | 404 | service | yes | 3 |
| T-SVC-047 | Product capture | product, PNG | `UploadCapture(product_id, target_date)` | `target_date` dropped, no follow-up queued, listed by `product_id`, absent from the day context | service | yes | 3 |
| T-SVC-048 | Product capture ownership | Bob's context / unknown id | `UploadCapture(product_id)` | 404 | service | yes | 3 |
| T-SVC-049 | Capture re-link | text capture | `UpdateCapture(product_id)` set and cleared | `product_id` follows | service | yes | 3 |
| T-SVC-050 | Proposal approve | product, label capture | `ProposeProductChange` then `DecideProposal(approve, changes)` | values applied, `verified` true, capture processed, second decision 409 | service | yes | 3 |
| T-SVC-051 | Proposal reject | pending proposal | `DecideProposal(approve=False)` | product unchanged, capture discarded; foreign tenant 404; non-proposable field 422 | service | yes | 3 |
| T-SVC-052 | Capture delete | image capture | `DeleteCapture` | capture and orphan blob gone; an assigned capture gives 409 | service | yes | 3 |
| T-SVC-053 | Discard retention | capture discarded 2 days ago | `ListCaptures` | purged automatically; still listed inside the retention window | service | yes | 3 |
| T-SVC-054 | Prompt echo | transcript empty or all vocabulary words | `TranscribeCapture` | transcript stored empty, capture `failed`, audit entry | service | yes | 3 |
| T-API-026 | Proposal endpoints | product + product capture | list, approve with correction | 200 with diff, product verified, capture processed, re-decide 409 | api | yes | 3 |
| T-API-027 | Proposal isolation | Alice's proposal | Bob lists / unknown id | empty list / 404 | api | yes | 3 |
| T-SVC-055 | Accept one item | day with two drafted items | `ApproveLineItem` with a correction | item accepted, day stays draft, capture still assigned; second call 409 | service | yes | 3 |
| T-SVC-056 | Last item accepted | one drafted item left | `ApproveLineItem` | day leaves draft, becomes reliable, capture processed | service | yes | 3 |
| T-RPT-010 | Timeline block | seeded days and weights | render a definition with `timeline` | one row per period day, the rolling window as configured, corridor bounds present | reports | yes | 2 |
| T-SVC-063 | Rules | settings saved | upsert twice with the same `when`, list, filter by scope | replaced instead of duplicated, priority order, tenant isolation, each change a settings version | service | yes | 3 |
| T-SVC-064 | Rule validation | blank `when`, unknown scope | `UpsertRule` | 422; `rules_markdown` renders the agent section | service | yes | 3 |
| T-SVC-061 | Product usage | product logged on two days | `GetProductUsage` | newest day first, totals, foreign tenant 404 | service | yes | 1 |
| T-SVC-062 | Portion after re-assignment | item with a count portion | `UpdateLineItem(consumable_id, unit)` | the new product's portion is used, not the old one | service | yes | 1 |
| T-SVC-057 | Freeze a report | rendered result | `FreezeReport` twice | newest first, list without payload, detail with payload, empty result 422 | service | yes | 2 |
| T-SVC-058 | One assessment | frozen snapshot | `AssessSnapshot` twice | text trimmed and stored, second call 409, blank 422, foreign tenant 404 | service | yes | 3 |
| T-SVC-059 | Delete a snapshot | frozen snapshot | `DeleteSnapshot` | gone | service | yes | 2 |
| T-SVC-060 | Active goal | legacy `goal`, `goals` with an active entry | `settings_from_data` | the active goal drives the settings; without a flag the first wins | service | yes | 2 |
| T-MCP-008 | captures_open scope | one product capture, one day capture | `captures_open(scope=product|day|all)` | product scope returns only captures with `product_id`; day scope none of them | registry | yes | 3 |
| T-MCP-009 | product_update from label | product + capture | `product_update(kcal, protein, source)` then `capture_mark(processed)` | values written, `verified=false`, `source` kept, capture processed | registry | yes | 3 |
| T-MCP-007 | stdio smoke | installed CLI | `victus mcp --help`, `victus agent --help` | commands and flags listed; exit 0 | – | yes | 3 |

## E2E (`T-E2E`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-E2E-001 | Login with passkey | dev stack, seeded tenant `alice`, Playwright virtual authenticator | open app → login | dashboard visible; cookie set | seed | yes | 1 |
| T-E2E-002 | Log a day | logged in | add meal, search product, add item, close day | day shows computed macros; `countable_days` includes it | seed | yes | 1 |
| T-E2E-003 | Approve a draft | seeded draft | open Drafts → correct quantity → approve | day closed; audit entry visible in history | seed | yes | 3 |
| T-E2E-004 | Manual weight entry | logged in | add weight | listed with `manual` badge; delete works; scale_sync rows have no delete button | seed | yes | 1 |

## Migration (`T-MIG`)

Victus has no importer (ADR 0011); migration means producing a backup archive and restoring it.

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-MIG-001 | Archive round-trip | tenant with products, days, weights | `backup create` → `backup verify` → `backup restore` into an empty database | row counts per table equal the manifest; computed day macros identical | factories | yes | 1 |
| T-MIG-002 | Foreign archive | hand-written JSONL following MIGRATION.md (minimal: tenant, unit, consumable, product, day_log, meal, line_item) | `backup verify`, `backup restore` | accepted; days appear with computed macros; missing required column is refused with a clear message | inline | yes | 1 |
| T-MIG-003 | Schema drift | archive with an unknown column | `backup verify` | refused, column named | inline | yes | 1 |
| T-MIG-004 | Tenant isolation on restore | archive of tenant A restored while tenant B exists | restore | B untouched; A's rows scoped to A | factories | yes | 1 |

## Operations (`T-OPS`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-OPS-001 | Backup create | seeded DB with blobs | `backup create --tenant alice` | ZIP with manifest, one JSONL per table, blobs by hash; manifest counts equal DB counts | temp dir | yes | 1 |
| T-OPS-002 | Backup verify | archive | `backup verify` | exit 0; tampered JSONL → exit 1 with table name | temp dir | yes | 1 |
| T-OPS-003 | Restore round trip | archive, empty DB | `backup restore` | row counts and a sample of rows identical; FK check passes | temp dir | yes | 1 |
| T-OPS-004 | Restore into another tenant | archive | `restore --as alice-test` | new tenant with same counts; original untouched | temp dir | yes | 1 |
| T-OPS-005 | Cross-dialect restore | SQLite archive | restore into PostgreSQL (CI service) | counts identical | CI | yes | 1 |
| T-OPS-006 | Retention | 30 archives with dates | `backup prune` | keeps 7 daily / 8 weekly / 12 monthly + newest + failed-verify | temp dir | yes | 3 |
| T-OPS-007 | Health backup age | old archive only | `GET /health` | `backup_age_hours` > threshold → `warn` | temp dir | yes | 1 |
| T-OPS-008 | Compose smoke | `docker compose up` (CI) | wait for health | `api`, `web`, `worker` healthy; `/health` 200 through `web` | CI | yes | 0–1 |
| T-OPS-009 | Migration downgrade | head | `alembic downgrade -1 && upgrade head` | no error; row counts unchanged | temp DB | yes | 1 |
| T-OPS-010 | Restore drill (manual, quarterly) | production archive | follow BACKUP.md "clone" steps | app opens on the drill tenant; delete afterwards | – | manual | ops |
| T-OPS-011 | All-tenant archive | two tenants | `backup create --all`; restore into empty DB; restore again with `--mode merge_new` | both tenants restored; second run inserts nothing, counts unchanged | temp dir | yes | 1 |
| T-OPS-012 | Replace mode | archive of alice; alice's line items deleted | `restore --mode replace` | alice's rows swapped back, computed macros restored; bob untouched; `fail_if_exists` refused beforehand | temp dir | yes | 1 |
| T-OPS-013 | Dry run | archive, empty DB | `restore --dry-run` | full import performed, counts reported, database still empty | temp dir | yes | 1 |
| T-OPS-014 | Scheduler cycle | seeded DB | `backup schedule --once`; daemon loop with fake clock | archive + verification + `backup_job` row (`finished`, verified); alive marker written; loop waits for the cron slot | temp dir | yes | 1 |
| T-OPS-015 | Cron parser | – | parse `0 3 * * *`, `*/15 * * * *`, `0 4 * * 0`, invalid expressions | correct `next_after`; 4-field and out-of-range expressions rejected | inline | yes | 1 |
| T-OPS-016 | Scoping coverage | ORM metadata | `scoping.check_coverage()` | every table is global, carries `tenant_id` or has a parent mapping — a new table without one fails this test | inline | yes | 1 |

## Reference values

| Item | Detail |
|---|---|
| Source | The predecessor's report script (private) run once on a **synthetic** daily weight and kcal series derived from — but not equal to — real data (shifted, scaled, re-dated) |
| File | `tests/fixtures/tdee_reference.json`: `{inputs: {daily_weight, daily_kcal, daily_protein, kcal_per_kg, goal}, expected: {weeks, rolling, trends, forecast, years, burndown}}` |
| Frozen | Date and script revision recorded in the file header |
| Tolerances | TDEE ±1 kcal, slopes ±0.0005 kg/day, weights ±0.01 kg |
| Re-freezing | Only with a `CHANGELOG.md` entry explaining the intended change; the PR must show the diff of expected values |

## Running the tests

```bash
uv run pytest                                # everything except e2e and ops-manual
uv run pytest -m domain                      # pure functions only (fast)
uv run pytest -m "service or api" --db sqlite
uv run pytest -m "service or api or migration" --db postgres   # needs DATABASE_URL_TEST
uv run pytest -m ops
uv run ruff check . && uv run mypy src/victus/domain src/victus/application
cd web && npm test                           # Vitest
cd web && npx playwright test                # needs the dev stack: docker compose --profile dev up
```

CI runs the Python matrix (3.12–3.14 × SQLite/PostgreSQL), lint, type check, Angular build and unit tests, Compose
smoke, security scans (`.github/workflows/`).

## Manual acceptance per stage

### Stage 0
- [ ] `uv run victus --version` prints the version from `pyproject.toml`
- [ ] `cd web && npm ci && npm run build` succeeds
- [ ] CI green on `main`
- [ ] `grep -rniE "<personal terms>" .` finds nothing outside LICENSE/author fields

### Stage 1
- [ ] Dry-run import of the operator's vault: report readable, review list plausible
- [ ] Real import; `countable_days` count equals the expected number of closed reliable days
- [ ] Two passkeys registered from two devices over HTTPS; recovery code stored
- [ ] One day logged end-to-end in the web app on a phone
- [ ] `backup create` → `verify` OK; `/health` shows `backup_age_hours`

### Stage 2
- [ ] `checkup` Markdown compared side by side with the predecessor's status output for the same window
- [ ] Dashboard renders every block on desktop and phone
- [ ] Reference tests green on both dialects

### Stage 3
- [ ] Voice note → capture → worker run → draft visible in app and via `drafts_list`
- [ ] Chat summary → `day_approve` → day closed; audit log lists the corrections
- [ ] External runner (Claude Code over HTTP MCP) processes a day while the worker is paused; then both enabled — no double draft
- [ ] Cost of a typical run recorded and below budget
- [ ] Weekend catch-up (3 days) shows three `agent_session` rows; no item in day 2's draft references a product only mentioned on day 1
- [ ] Type a correction on a drafted day in the app → follow-up run changes only that item; type a message while a run is active → shown as "waiting for the agent", processed after the lock is released
- [ ] Agent page: the run appears with sessions and cost; **Cancel** on a queued run works; **Force unlock** asks for confirmation first
- [ ] Captures page: a duplicate upload shows the notice and adds no row; **Set day** on an undated voice note makes it eligible for the next run; **Re-transcribe** replaces a bad transcript
