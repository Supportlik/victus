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

### Look at what you changed

**Every area a change touched, and every area that follows from it, is opened in a browser and looked at before
the change is called done.** Not instead of the automated levels — after them.

This is a rule because the suite cannot see the class of fault that reaches people. A timestamp cut out of a
stored ISO string passed every test and told a reader in Berlin the wrong hour and, after midnight, the wrong
day. Two English sentences sat on a German page because a ternary chose them inside the call the translation
check reads. A recording showed 0:00 because the player was told to preload nothing. A day left on the default
training option had no target band at all, so its gauges were missing and its macros went unrated. None of these
is subtle. All of them are invisible to a passing assertion and obvious on the page.

Follow the change through, not just to it: a band is checked on the day **and** in the report that rates days; a
portion is checked on the product page **and** in the add-item list that offers it; a translation is checked in
the language that lacks it, not in English.

For widths, use the browser's device emulation. Resizing a maximised window silently does nothing, and a layout
claimed rather than seen is worth nothing.

And when something could not be checked, say so. An unverified area reported as verified is worse than an
unverified area reported as unverified.

## Conventions

| Item | Rule |
|---|---|
| ID | `T-<LEVEL>-<3 digits>`, stable; retired cases are marked *retired*, never renumbered |
| pytest marker | `@pytest.mark.<level>` (`domain`, `importer`, `service`, `api`, `agent`, `mcp`, `migration`, `ops`) |
| DB matrix | `--db sqlite` (default) and `--db postgres` (service container in CI) for `T-SVC`, `T-API`, `T-MIG` |
| Fixtures | Synthetic or anonymised; no real personal or health data (SPEC R48) |
| Tolerances | kcal ±1, macros ±0.1 g, salt ±0.01 g, weight ±0.01 kg, TDEE ±1 kcal unless stated |
| Manual check | Every area a change touched, and every area downstream of it, opened in a browser and looked at before the change is done (see *Look at what you changed*) |

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
| T-DOM-029 | Links in a quantity, and bracket storms | `[[foods\|Skyr]] 300 g`, `[Label](url)`, an unclosed link, and 30 000 × `[[` | `clean_text` | label kept, unclosed link left as text, storm returned unchanged in well under a second (linear, not one scan per bracket) | inline | yes | 1 |
| T-DOM-030 | Parenthesis stripping on a hostile name | `Kartoffel (roh)` and 30 000 × `(` | `matching.short_form` | short form as before; the storm costs milliseconds | inline | yes | 1 |
| T-DOM-080 | Domain | `services/calendar` | Moments either side of local midnight, winter and summer, naive timestamps, an unknown zone | The day follows the zone; bounds are UTC moments of the local day; an unknown zone falls back to the default | `test_calendar.py` | automated |
| T-DOM-081 | Domain | `services/body` BMI | Values either side of every class boundary, and classes as kilograms at 170 cm | Boundaries are inclusive below and exclusive above; the distance to the next better class is in BMI points | `test_body.py` | automated |
| T-DOM-082 | Domain | Waist ratios | Waist to height and waist to hip for both sexes | Each uses its own scale, and the waist-to-hip thresholds differ by sex | `test_body.py` | automated |
| T-DOM-083 | Domain | Resting rate | Mifflin-St Jeor for both sexes, and the age boundary on a birthday | Matches the published equation; the birthday itself counts | `test_body.py` | automated |
| T-DOM-084 | Domain | Energy split | Expenditure at 1.09, 1.6 and 2.51 times resting | The middle one splits cleanly; the outer two carry a caveat naming bed rest or athletes | `test_body.py` | automated |
| T-DOM-085 | Domain | `services/search_ranking` | Rank `Ei` against the name itself, a first word, a later word, a syllable, a brand and an umlaut spelling; sort a list of them | Each falls in its own tier, an umlaut does not demote the exact answer, a brand hit ranks below every name hit, and sorting puts the named product first | `test_search_ranking.py` | automated |
| T-DOM-086 | Domain | `services/units` density | Convert g↔ml at 1.32 and 0.92, the same unit twice, a missing, zero and negative density, and a count unit | The two units convert through the density; the same unit comes back untouched; anything the density cannot relate is `None`, never the amount itself | `test_units.py` | automated |

## Tooling (`T-TOOL`)

Checks that guard the repository's own scripts. They run with the domain marker because they
need nothing but files.

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-TOOL-001 | The translation check finds the key | a call written plainly, with a ternary, with parameters, with a fallback, and around a nested call | `check_translations._keys_in` | both ternary branches are keys, the condition and a nested call's arguments are not | inline | yes | 1 |
| T-TOOL-002 | Literals are read by scanning | escaped quotes, an unclosed quote, a quote followed by 26 escape pairs, and a dictionary with quoted, bare, escaped and unterminated keys | `_keys_in`, `translated` | the escape stays inside the key, an unclosed quote yields no key, and the storm returns in milliseconds instead of backtracking | `tmp_path` | yes | 1 |

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
| T-API-023 | Audio upload transcribes | fake transcription | `POST /captures` with an audio file, then with two | 201, `transcript` filled and one `transcripts` entry per recording with its length; with a failing provider the capture is `failed` and the upload still 201 | client | yes | 3 |
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
| T-WEB-033 | Web | Capture form on the inbox | Type a line and save without picking any file | One text box and one "Save capture" button exist; the button is disabled while empty, posts `text` plus `target_date` and no file, then clears the form | `capture-input.spec.ts` | automated |
| T-WEB-034 | Web | Timeline tooltip | Hover any of the three panels for one day, then a day without a weigh-in | The same tooltip from every panel in a fixed order: 7-day average, weigh-in, intake, TDEE, macros; the weigh-in line appears only when the scale was used that day | `report-block.spec.ts` | automated |
| T-WEB-035 | Web | Tenant settings form | Read and write `captures.processed_retention_days` | 30 round-trips; `0` is written as `0`; an empty field drops the whole `captures` object | `settings-form.spec.ts` | automated |
| T-WEB-036 | Web | Inbox header | Load the page with runner `ready`, then with `no_key` | `ready` shows Process now; `no_key` shows Open Claude for Processing and lists only the unassessed frozen report | `inbox-page.spec.ts` | automated |
| T-WEB-037 | Web | Phone navigation | Render the shell signed in, then press More | Six entries in the bar; the sheet lists the four remaining sections plus sign out; a recovery session shows no bar at all | `app.spec.ts` | automated |
| T-WEB-038 | Web | Report tooltip | Adopt `de-DE`, then `en-GB` | The same values read 89,4 / 1.900 and 89.4 / 1,900 | `report-block.spec.ts` | automated |
| T-WEB-039 | Web | Product search | Set `on` and type a query | The request carries `on`, so an older day is offered the values of its time | `product-search.spec.ts` | automated |
| T-WEB-040 | Web | Inbox, frozen report | Press Assess now with runner `ready` | Queues one run with mode `assess` | `inbox-page.spec.ts` | automated |
| T-WEB-041 | Web | Day view, unit picker | Pick a product without portions, choose the count unit `bag`, give 500 g | The picker groups the units, asks what one bag holds, posts the portion first and then the item against it | `day-view.spec.ts` | automated |
| T-WEB-042 | Web | Body block | Render a BMI in class I with its scale | One segment per class, the current one marked, the pin inside the bar, the kilogram row highlighted, a shrinking waist shown as an improvement | `report-block.spec.ts` | automated |
| T-WEB-043 | Web | Weight page | List measurements, submit a partly filled form, render with and without a height | Newest first with dashes for unmeasured values; the request carries only what was filled in; six shaded bands with a height, none without | `weight-page.spec.ts` | automated |
| T-WEB-044 | Web | Interface language | Switch to German, ask for an unknown string, fill a placeholder, offer a language that is not shipped | Translates once switched; an unknown string comes back unchanged; placeholders fill; an unknown language falls back and the choice is mirrored | `i18n.service.spec.ts` | automated |
| T-WEB-045 | Web | Floating notices | A success, an error, and a fourth message | The success clears itself after four seconds, the error survives a minute and goes only on dismiss, the oldest of four is dropped | `notice.service.spec.ts` | automated |
| T-WEB-046 | Web | Body measurement table | Two sessions where five measures were never taped, then a value nulled on the newest | Only the taped measures appear, newest session first, the shrinking waist green; a nulled value and its change both read as a dash | `weight-page.spec.ts` | automated |
| T-WEB-055 | Web | The day's verdict | Render a day without a verdict, then with one | Nothing is shown without one; with one it stands above the meals, outside the thread | `day-view.spec.ts` | automated |
| T-WEB-056 | Web | Editing a logged item | Open the edit panel on the day and on the draft approval, clear both estimate marks, then set one and pick a portion | The panel opens on what the item says, the unit list carries the product's own portions, and the patch sends amount, unit, portion and both marks — `false` included | `day-view.spec.ts`, `draft-approval.spec.ts` | automated |
| T-WEB-047 | Web | Products page paging | Answer the first request with a full page, press Load more, answer with a short page; then a short first page | The first request carries `limit` and `offset`, the next one the offset of what is loaded, rows are appended, and the button gives way to the count once the last page arrived | `products-page.spec.ts` | automated |
| T-WEB-050 | Web | Recordings on a capture card | Render a capture of two recordings where one is transcribed, then one silent and one spoken, then a payload with only the capture-wide text | Each recording has its own player with `preload="metadata"`, its length and its text; an untranscribed one says so instead of borrowing its neighbour's; silence and waiting read differently; a capture-wide text is read as the first recording's | `capture-card.spec.ts` | automated |
| T-WEB-060 | Web | A correction in the products list | List a pending correction to `carbs` with the product answered from the API | The row reads 42 → 8 g rather than the field name, the five unchanged numbers and the reference amount stand beside it, the line-item count is printed, and Approve, Reject and a link to that one proposal sit in the row | `products-page.spec.ts` | automated |
| T-WEB-061 | Web | A new product in the products list | List a pending `new` proposal whose one-off was logged on a day | Its values, brand and portion are shown, and the day it was eaten on is a link, with the meal, the amount as logged and the draft tag | `products-page.spec.ts` | automated |
| T-WEB-062 | Web | Proposal timestamp and anchor | Render a product whose proposal was stored at 22:30 UTC, with the tenant in Europe/Berlin | The time reads 00:30 on the following day rather than the sliced ISO string, `datetime` keeps the instant, and the proposal carries an id the list can link to | `product-detail.spec.ts` | automated |
| T-WEB-066 | Web | The density on the product page | Render a product with 1.32 g/ml and one without | The value is printed with its unit and what it converts, outside the six nutrients; without one the page says so, which is why grams will be refused | `product-detail.spec.ts` | automated |
| T-WEB-067 | Web | A refused portion leads to the density | Answer the portion POST with the 422 the API sends, then press what it offers | The sentence gives way to an offer, pressing it opens the editor with the caret in the density field, and the refusal is gone | `product-detail.spec.ts` | automated |
| T-WEB-070 | Web | The change stream | Open it, deliver `hello` and a `change`, fail it while the browser is still retrying, then fatally, then let it fall silent past the heartbeat; finally take `EventSource` away | One stream per session; counts and targets published; a payload that will not parse is dropped and the last good change stands; the browser's own retry is left alone and a stream it gave up on is reopened with backoff, counting as a reconnect; silence past a minute reopens it too; without `EventSource` the state is `offline` and nothing breaks | `live.service.spec.ts` | automated |
| T-WEB-071 | Web | The day and the change stream | Deliver a change naming this day, one naming the day after, and one while the add-item form is open | The day is fetched again silently; the other day's change is ignored; with the form open nothing on screen is replaced, a dismissible notice says there is newer data, and pressing Show it fetches then | `day-view.spec.ts` | automated |
| T-WEB-072 | Web | The API line in the navigation rail | Answer `/health` with a failure, then let the stream connect; separately, let a standing stream fail | The line reads “API unreachable” with a red dot while the rail, the tenant and the routed view stay on screen; the stream standing makes the line ask again and heal to the version; a stream that was live and is away reads “Reconnecting…” without asking the API anything | `app.spec.ts` | automated |
| T-WEB-073 | Web | Navigation badges and the stream | Start the badges, connect the stream with counts, advance a minute; then with no stream at all; then let a live stream drop | While live the four numbers come from the stream and no request is made; with no stream the minute poll does the work it always did; a dropped stream puts the poll back | `badges.service.spec.ts` | automated |
| T-WEB-074 | Web | The products page and the stream | Load with no proposals, then deliver a `product_proposal` change | The proposal and its evidence are fetched and shown without a reload and without a notice, because nothing was being decided | `products-page.spec.ts` | automated |
| T-WEB-075 | Web | The inbox and a half-written capture | Type into the capture box, then deliver a `capture` change | Nothing is fetched and the typed line is untouched; the notice offers the newer data and pressing Show it loads it | `inbox-page.spec.ts` | automated |
| T-WEB-033 | Day thread states | mocked messages with `processing_state` and agent kinds | render `DayThread` | user captures show "waiting for the agent" / "in draft"; agent messages tagged question/note — the day's verdict is not a chat entry; composer enabled while a run is active | mock | partly (manual) | 3 |

## Agent (`T-AGT`)

| ID | Title | Precondition | Steps | Expected | Fixture | Automated | Stage |
|---|---|---|---|---|---|---|---|
| T-AGT-001 | Registry schemas | – | build Anthropic tool definitions from `mcp/tools.py` | every tool has a name, description and a valid JSON schema; scopes assigned | inline | yes | 3 |
| T-AGT-002 | Dispatch and scopes | tool context with `read` only | dispatch `product_search`, then `draft_create` | first returns candidates; second rejected with a scope error before the use case runs | in-memory SQLite | yes | 3 |
| T-AGT-003 | Worker end to end | tenant, product with portion, text capture for a day, `ScriptedModelClient` (product_search → draft_create → end_turn) | `QueueAgentRun`, `Worker.run_once()` | `day_log` draft with `is_draft` items, one `agent_session` row, run `finished` with a summary containing the day header, capture `assigned`; afterwards `day_approve` → capture `processed` | scripted model | yes | 3 |
| T-AGT-004 | One session per day | captures for three days | `Worker.run_once()` | three `agent_session` rows; each session's messages contain only that day's captures | scripted model | yes | 3 |
| T-AGT-005 | Budget exceeded | `max_usd_per_run` below the first session's cost | run | run `budget_exceeded`, remaining days unlocked, summary explains | scripted model | yes | 3 |
| T-AGT-006 | Refusal | scripted `stop_reason=refusal` | run | session outcome `refused`, day not drafted, run `finished` with the note in the summary | scripted model | yes | 3 |
| T-AGT-007 | Agent | `assess` run | Freeze a report, queue an assess run, script `report_assess` | The snapshot is assessed with the runner's prompt version, the summary names it, and no day is locked | `test_runner.py` | automated |
| T-AGT-008 | Agent | `assess` run, nothing waiting | Queue an assess run with no frozen report | Finishes without calling the model and says so | `test_runner.py` | automated |
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
| T-SVC-054 | Prompt echo | transcript empty, made of vocabulary words, or repeating twelve of the prompt's words in the prompt's order — of any length, including the whole prompt | `TranscribeCapture`, `looks_like_prompt_echo` | transcript stored empty, capture `failed`, audit entry; a long genuine note that names known foods is not an echo | service | yes | 3 |
| T-API-026 | Proposal endpoints | product + product capture | list, approve with correction | 200 with diff, product verified, capture processed, re-decide 409 | api | yes | 3 |
| T-API-027 | Proposal isolation | Alice's proposal | Bob lists / unknown id | empty list / 404 | api | yes | 3 |
| T-API-070 | API | `GET /agent/status` | Toggle `agent.enabled` and the model key | Reports `disabled`, `no_key` and `ready`; the model name appears only when ready, never a key | `test_agent_api.py` | automated |
| T-API-071 | API | Product versions over HTTP | POST a version, read the history, search with and without `on` | 201 with the new row, the old one closed, one hit per day | `test_routers.py` | automated |
| T-API-072 | API | `GET /products` paged and ranked | Read the catalogue in windows of two, ask past the end, send a negative offset, then search `Ei` | Consecutive windows, a short last page, an empty page past the end, 422 for a negative offset, and the product named "Ei" first | `test_routers.py` | automated |
| T-API-073 | API | A portion operation over HTTP | Propose an update to a portion, list the proposals, then approve | The list carries a `portion_plan` naming the row it changes and that nothing refuses it; after the approval the portion holds the new weight and the plan is empty | `test_proposals_api.py` | automated |
| T-API-075 | API | A density over HTTP | POST a product with `density_g_per_ml`, read it back and list it, POST one without, add a gram portion to it, then PATCH a density in and add the portion again | Every answer carries the field — null where there is none — the refusal's problem names `density_g_per_ml` in `errors` beside the sentence, and after the PATCH the same portion is created | `test_routers.py` | automated |
| T-API-076 | API | A connect says where the tenant stands | Open `GET /events` with a seeded capture and one unfinished past day | `hello` carries the current cursor as `id:` and as `cursor`, the four counts, no `targets`, and the response is `text/event-stream` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` | `test_events_api.py` | automated |
| T-API-077 | API | A write while connected is pushed | Create a day from another thread once the stream is open | A `change` arrives naming `day.create` on `day_log`, with a higher cursor as `id:`, `truncated: false`, and the counts already updated | `test_events_api.py` | automated |
| T-API-078 | API | A reconnect resumes | Reconnect with `Last-Event-ID`, then with `?cursor=`, then from the current cursor | Both greet at that cursor and replay only the missed entry; from the current cursor nothing is replayed and only heartbeats follow | `test_events_api.py` | automated |
| T-API-079 | API | Another tenant's writes never appear | Bob writes while Alice listens | Alice's stream carries `hello` and heartbeats only, all on her unchanged cursor | `test_events_api.py` | automated |
| T-API-080 | API | The stream carries no diff | Trigger `day.create`, which books a diff, and read every frame | A target holds `action`, `type` and `id` and nothing else; neither the word `diff` nor the diff's date appears anywhere in the stream | `test_events_api.py` | automated |
| T-API-081 | API | Refusals | No principal, an unknown bearer, a `read`-only token, and `events.enabled: false` | 401, 401, 403, and a `503` problem+json titled "Feature disabled" — never a connection that hangs | `test_events_api.py` | automated |
| T-SVC-055 | Accept one item | day with two drafted items | `ApproveLineItem` with a correction | item accepted, day stays draft, capture still assigned; second call 409 | service | yes | 3 |
| T-SVC-056 | Last item accepted | one drafted item left | `ApproveLineItem` | day leaves draft, becomes reliable, capture processed | service | yes | 3 |
| T-RPT-010 | Timeline block | seeded days and weights | render a definition with `timeline` | one row per period day, the rolling window as configured, corridor bounds present | reports | yes | 2 |
| T-SVC-065 | One capture, several files | two photos and a voice note | `UploadCapture(files=…)` | one capture with three ordered attachments, kind audio, re-upload is a no-op, delete removes every orphan blob | service | yes | 3 |
| T-SVC-066 | Service | Capture retention | Age a processed capture past the retention, then list captures | Capture and its blob are gone; with `processed_retention_days: 0` a 400-day-old capture stays | `test_proposals_and_capture_lifecycle.py` | automated |
| T-SVC-067 | Service | Weigh-in day boundary | Add a reading at 23:30 UTC with the tenant on Europe/Berlin, then on UTC | It counts on the 6th in Berlin and on the 5th in UTC | `test_days_and_drafts.py` | automated |
| T-SVC-068 | Service | New product version | Create a version from 2026-06-01 with a new kcal | The new row is open ended, copies portions and untouched values, and closes the old one on 2026-05-31 | `test_product_versions.py` | automated |
| T-SVC-069 | Service | Version resolution | Search with `on` before and after the change, and without | Each day resolves to exactly one version; without a day the current one | `test_product_versions.py` | automated |
| T-SVC-070 | Service | Version guards | Chain a third version, then try to start one before its predecessor and from a superseded row | The chain reads oldest first; the two attempts fail with a validation error and a conflict | `test_product_versions.py` | automated |
| T-SVC-071 | Service | Body measurement | Record waist and hip only, then repeat the timestamp, then send nothing and a typo | Unmeasured values stay null; a repeated timestamp conflicts; an empty session and 1264 cm are refused | `test_body_measurements.py` | automated |
| T-SVC-072 | Service | Body profile | Read the profile with no settings, with all three fields, and with height only | Returns what is there and None for the rest, never raising | `test_body_measurements.py` | automated |
| T-SVC-073 | Service | Write proposes | Same day, one item added with approve and one without | The person's item is a fact, the agent's arrives as a draft | `test_scope_boundary.py` | automated |
| T-SVC-074 | Service | Facts are out of reach | Agent scopes try update, delete, close_day and `reliable` on approved data | Every call raises `ScopeError`; the day is unchanged | `test_scope_boundary.py` | automated |
| T-SVC-075 | Service | Withdraw a draft | Plain `write` and then `agent:write` delete the agent's own draft | `write` is refused, `agent:write` may take its proposal back | `test_scope_boundary.py` | automated |
| T-SVC-076 | Service | New product proposes | `create_or_propose_product` with agent scopes, then `CreateProduct` directly | A pending `new` proposal with a loggable consumable; the catalogue stays empty; the direct write is refused | `test_scope_boundary.py` | automated |
| T-SVC-077 | Service | Promotion in place | Log the pending one-off, then approve the proposal | Same id becomes the product with its portion and `verified`; the line item is untouched and the product is searchable | `test_scope_boundary.py` | automated |
| T-SVC-078 | Service | Rejection keeps the meal | Log the one-off, agent tries to decide, person rejects | The agent is refused; after rejection the meal keeps its macros and no product exists | `test_scope_boundary.py` | automated |
| T-SVC-085 | Service | One verdict per day | Write a `summary` for a day, a note beside it, then a second `summary` | The second verdict replaces the first, the note stays, the day view carries the current one; a blank verdict and an unknown kind are refused | `test_agent.py` | automated |
| T-SVC-079 | Service | Ranked search | Search `Ei` with ten products whose names contain those letters, then `Öl`, which `LIKE` cannot match | The product named "Ei" comes first and the syllable hits follow alphabetically; the fuzzy tier contributes on every query, so the umlaut is found | `test_product_search.py` | automated |
| T-SVC-080 | Service | Paged catalogue | List 25 products in windows of ten, ask past the end, then page a ranked query | Every row is reached exactly once, an offset past the end is empty, and paging a query yields the ranked order | `test_product_search.py` | automated |
| T-SVC-081 | Service | Two recordings, two transcripts | Transcribe a capture of a voice note, a photo and a second voice note | One transcript per recording, each keyed to its file and carrying its length; the photo never reaches the provider; the joined `transcript` holds both texts; a second call transcribes nothing, `force` both again | `test_captures.py` | automated |
| T-SVC-082 | Service | A transcript without a recording | Store a transcript with no `attachment_id` on a capture of two notes, then transcribe | It is shown under the first recording, the second says it is waiting, and transcribing reads only the second | `test_captures.py` | automated |
| T-SVC-083 | Service | A portion in the other unit | Log one 20 g spoonful of a syrup stated per 100 ml at 1.32 g/ml, then 132 g of it, then 10 ml of an oil stated per 100 g at 0.92 | Each item is frozen in the product's own unit — 15.15 ml, 100 ml, 9.2 g — and the kcal follow (39.4, not 52); the amount stays as entered | `test_portion_units.py` | automated |
| T-SVC-084 | Service | No density, no way out | Add a 250 g portion to a juice stated per 100 ml, switch a millilitre portion to grams, then set a density and add the gram portion again | Both attempts are refused naming the density; with a density the portion is accepted and 210 g resolves to 200 ml | `test_portion_units.py` | automated |
| T-SVC-086 | Service | Ingredient before the batch freezes | Cook a recipe with 200 ml of an oil stated per 100 g at 0.92 | The frozen batch holds 1626.56 kcal — 184 g of oil, not 200 | `test_portion_units.py` | automated |
| T-SVC-090 | Service | Usage of a pending one-off | Propose a new product, log its one-off twice on a day, then ask for its usage with `limit=1` | The day, the meal and the amount come back for the one-off, and `item_count` says two although one entry was asked for | `test_proposals_and_capture_lifecycle.py` | automated |
| T-SVC-091 | Service | A portion correction proposes | An actor with `write` but not `approve` calls `UpdatePortion`/`DeletePortion`, then proposes both | The direct calls raise `ScopeError`; both become pending proposals carrying `op`, with the row they change and its usage; the catalogue is unchanged | `test_portion_proposals.py` | automated |
| T-SVC-092 | Service | Approval applies just that | Approve the update and the delete of the twin portion | The wrong row is corrected in place, the duplicate is gone, and no third portion appears | `test_portion_proposals.py` | automated |
| T-SVC-093 | Service | A portion entry without an `op` | Store a proposal in the old shape (no `op`) and approve it | It is applied as an add, as it was before the operations existed | `test_portion_proposals.py` | automated |
| T-SVC-094 | Service | Deleting a portion in use | Log an item against the portion, propose the delete, then approve | The pending proposal names the refusal and counts the item; approving is refused, the portion stays and the proposal stays pending | `test_portion_proposals.py` | automated |
| T-SVC-095 | Service | A swap in one proposal | One proposal deletes the wrong-unit twin and adds the right portion under the same unit and label | Neither line is blocked — the plan reads in the order it applies — and the approval leaves exactly the corrected portion | `test_portion_proposals.py` | automated |
| T-SVC-096 | Service | A new version proposes | An actor with `write` but not `approve` calls `NewProductVersion`, then goes through the door | The direct call raises `ScopeError`; the door files a pending `kind='version'` proposal carrying `valid_from` and the changed fields, and the catalogue still has one version | `test_version_proposals.py` | automated |
| T-SVC-097 | Service | Approving opens the version | Log a tub on a day before the change, then approve the version proposal | The new version starts on `valid_from` open ended and copies the portions; the old one is closed the day before and the earlier day still counts 252 kcal | `test_version_proposals.py` | automated |
| T-SVC-098 | Service | What a version may not carry | Propose a version with `portions`, with no changed field, on the day its predecessor began, and against a version that has a successor | All four are refused while drafting, so no proposal exists that nobody could approve | `test_version_proposals.py` | automated |
| T-SVC-099 | Service | The door with `approve`, and the older kinds | Call the version door holding `approve`, then propose an `update` to the version it opened | The version is opened directly with nothing pending; the `update` proposal is still a correction in place — same id, no new row | `test_version_proposals.py` | automated |
| T-SVC-100 | Service | A version the chain outgrew | Propose a version, open one by hand, then approve the proposal | Approving is refused, the proposal stays pending and decidable, and rejecting it leaves the chain as the person left it | `test_version_proposals.py` | automated |
| T-SVC-101 | Service | Approving part of a version proposal | Approve a version proposal with `fields=['kcal']`, leaving `protein` out | The new version starts on `valid_from` all the same — the day is not a value under review — and the field left out keeps the old number | `test_version_proposals.py` | automated |
| T-SVC-102 | Service | A portion proposal for a unit that is not one | Propose adding `piece_s`, `piece_m`, `piece_l` and `piece_xl` — egg sizes written as unit codes — then approve each | Every plan line is blocked naming the code, saying a size belongs in the label and pointing at `piece`; each approval is refused, the proposals stay pending and no portion is added | `test_portion_proposals.py` | automated |
| T-SVC-103 | Service | An update to a unit that is not one | Propose an update setting `unit_code` to `tub_xl` | The plan names the code and points at `tub`; approving is refused and the row keeps its unit | `test_portion_proposals.py` | automated |
| T-SVC-104 | Service | A portion in a unit the product's values forbid | Propose a portion in `kg`, and one in `g` for a product stated per 100 ml, then set a density and read the plan again | The `kg` line says a portion is in g or ml; the `g` line carries the R75 message; with a density the same pending line is unblocked and approves | `test_portion_proposals.py` | automated |
| T-SVC-105 | Service | An amount that is not an amount | Propose an update to amount 0 and to `"half a tub"`, and store an add of −25 g by hand | Each line is blocked as needing a positive number; approving is refused and the portion keeps its weight | `test_portion_proposals.py` | automated |
| T-SVC-106 | Service | A `portion_id` that is not this product's | Propose an update naming another product's portion, and a delete of a portion a person removes first | The first says which product owns the row, the second that it no longer exists; approving the delete is refused | `test_portion_proposals.py` | automated |
| T-SVC-107 | Service | A portion entry in a shape no use case accepts | Store an unknown `op`, an update without `portion_id`, an update with no field and an add without `unit_code` | Each is blocked with the reason `_validated_portions` raises, and approving is refused before anything is applied | `test_portion_proposals.py` | automated |
| T-SVC-108 | Service | The reference a portion is read against | Propose moving `reference_unit` to `ml` together with two portions, and a `new` product per 100 ml with three | The plan is read against the values the proposal will have applied, not the ones the catalogue holds now: the millilitre portions are unblocked and the gram ones are not | `test_portion_proposals.py` | automated |
| T-SVC-109 | Service | A density a reader can see and reach | Read a juice stated per 100 ml, add a portion in grams, then set a density and read the product again | The view carries `density_g_per_ml` — null at first, 1.05 after — and the refusal carries `errors[0].field == 'density_g_per_ml'`, so a client can offer the field rather than name it | `test_portion_units.py` | automated |
| T-SVC-110 | Service | The four counts are the badges | Count an empty inbox, then one new capture, a day today, a day yesterday, a pending proposal and a second tenant's day; then close yesterday | `open_days` counts yesterday and not today, the other three follow their own rows, another tenant's writes are invisible, and closing the day takes it off the badge | `test_change_feed.py` | automated |
| T-SVC-111 | Service | A long backlog is capped and says so | Five catalogue writes, read the changes with the cap at five and at two, then from the current cursor | The full read carries five targets and `truncated: false`; the capped read keeps the newest two, sets `truncated`, and reports the same exact cursor; from the current cursor there is nothing | `test_change_feed.py` | automated |
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
| T-MCP-010 | MCP | Unknown food end to end | Agent scopes: `product_search` finds nothing → `product_create` → `draft_create` against the returned consumable → `day_approve` refused → person approves the proposal and the day | The product is a pending proposal and stays out of the catalogue; the day is drafted with the right macros; approval promotes the one-off in place and the very same item survives, now approved | `test_new_product_flow.py` | automated |
| T-MCP-012 | MCP | The day's verdict without a draft | `agent_run_start` → `agent_message_add(kind="summary")` → `day_get` | The verdict is written as the agent, nothing is drafted, and `day_get` returns it in `verdict` | `test_server.py` | automated |
| T-MCP-013 | MCP | Portion tools without `approve` | `portion_update` and `portion_delete` as an actor holding only `write`, then the same calls with `approve` | Both file pending proposals carrying the operation and the current row; with `approve` the portion is written and removed straight through | `test_product_tools.py` | automated |
| T-MCP-014 | MCP | `product_version_create` without `approve` | The tool as an actor holding only `write`, then the same call with `approve` | It files a pending `kind='version'` proposal with `pending_review` and leaves the product at 63 kcal; with `approve` the version is opened and `product_versions` shows both | `test_product_tools.py` | automated |
| T-MCP-015 | MCP | A portion proposal nobody could approve | `portion_create` with `unit_code='piece_s'` as an actor holding only `write`, then the same size as a `piece` with the size in the label | The first comes back pending with `blocked` naming the code and pointing at `piece`; the second is unblocked and approves into the catalogue | `test_product_tools.py` | automated |
| T-MCP-016 | MCP | A density the agent can see | `product_get` and `product_search` for a syrup at 1.32 g/ml and for a product without one, then `product_propose` of a density | Both tools carry `density_g_per_ml`, null where there is none, and the proposal's `current` holds the value under it, which is what the field was proposed against | `test_product_tools.py` | automated |
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
| T-OPS-017 | Ops | Upgrade with data | Migrate to 0010, store a capture of a photo and a recording with one transcript, then upgrade to head | The transcript is attributed to the recording, not to the photo `capture.attachment_id` names | `test_migration.py` | automated |
| T-OPS-018 | Ops | Widening the proposal `kind` CHECK | Downgrade to 0011 for a narrow constraint, store an `update` proposal, upgrade to head, then downgrade again | Before the upgrade `kind='version'` is refused; after it the row is accepted while `ck_product_proposal_status`, both indexes, all four foreign keys and the stored row survive the SQLite rebuild; the downgrade drops only the version rows | `test_migration.py` | automated |

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
