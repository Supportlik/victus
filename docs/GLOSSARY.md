# Glossary

Victus uses English identifiers everywhere ([SPEC.md](SPEC.md), D9). The importer reads a German-language Markdown
vault, so the last column lists the term as it appears in that source format.

| Term | Meaning in Victus | German source term |
|---|---|---|
| **day_log** | One day of eating for one tenant. Has `status` (`draft` / `open` / `closed`), `reliable`, `training_type`, a frozen `target_band_id` and the cross-check columns `source_*`. | Tagelog |
| **meal** | A named group of line items within a day (breakfast, lunch, …), ordered by `position`. | Mahlzeit |
| **line_item** | One food quantity in a meal. Holds the captured quantity (`quantity`, `unit_code`), the frozen base quantity (`base_quantity`, `base_unit`) and flags. **Never** holds nutrients. | Posten |
| **consumable** | Supertype of everything a line item can reference: `product`, `recipe_batch`, `ad_hoc_item`. `UNIQUE(id, kind)` makes the subtype FK safe. | Verzehrbar |
| **product** | A food with nutrients per 100 g or 100 ml, a `source`, a `verified` flag (1 = label/manufacturer, 0 = estimate), optional EAN. | Produkt |
| **portion** | A named piece weight of a product ("tub", "slice", "piece") with `quantity` in g/ml. The only place piece weights live; one default portion per product and unit. | Portion |
| **recipe** | Definition: ingredients and standard servings. Editing a recipe never changes past batches. | Rezept |
| **recipe_batch** | One cooking event of a recipe with total weight and **frozen** total nutrients; portions eaten reference the batch. | Rezept-Charge |
| **ad_hoc_item** | Something eaten once without a product record (restaurant plate, unmatched import row); nutrients stored on the item's own record, per 100 g. | Einmalposten |
| **unit** | Global master data: `mass` (g, kg), `volume` (ml, l), `count` (piece, slice, …). Count units need a portion to resolve. | Einheit |
| **category** | Product grouping per tenant. | Kategorie |
| **target_band** | One complete profile of min / optimal range / target / max / stretch per nutrient, valid from `valid_from`, per `training_type` (`rest`, `strength`, `martial_arts`). Salt lives **only** here. | Zielband |
| **reliable** | `true` = the day counts for TDEE and reports. `false` = the *user* estimated the whole day (travel, party). An agent estimate never sets it to false. | belastbar |
| **status `open`** | The day is still running and excluded from all statistics. | offen |
| **status `draft`** | Written by the agent, not yet approved, excluded from statistics. Also `line_item.is_draft = 1` for items added to an existing day. | Entwurf |
| **status `closed`** | The day is complete and approved; its `target_band_id` is frozen. | abgeschlossen |
| **estimated / quantity_estimated** | Item-level flags rendered as ⚠️; they survive approval. | geschätzt |
| **capture** | An inbox item: text, audio or image with a content hash, optional `target_date`, and processing status (`new`, `in_progress`, `assigned`, `processed`, `discarded`, `failed`). | Capture |
| **attachment** | The stored file behind a capture, addressed by SHA-256. | Anhang |
| **transcript** | Text produced from an audio capture, with provider, model and cost. | Transkript |
| **agent_run** | One processing job: runner, mode, tokens, cost, summary. | – |
| **agent_lock** | Per `(tenant, date)` lock so two runners never draft the same day. | – |
| **weight_entry** | One weigh-in with timestamp, kg and `source` (`scale_sync`, `manual`, `import`). | Gewicht |
| **kcal_per_kg** | Energy equivalent of one kilogram of body mass used by TDEE formulas (default 7716.17). | kcal pro kg |
| **TDEE** | Total daily energy expenditure: `Ø kcal intake + (−Δ weight × kcal_per_kg) / days`; computed weekly and over rolling windows with a quality grade. | TDEE |
| **review list** | Import output: line items the matcher could not assign, with top candidates; worked off in the app. | Klärliste |
| **round-trip gate** | Import check: a day passes when its computed kcal reproduce the Markdown frontmatter within 3 %. | Round-Trip-Gate |
| **balance section** | The Markdown table in a vault day log that the importer uses as cross-check (`source_*`). | Tagesbilanz |
| **check-up** | The built-in report "Am I on track?". | Checkup |
| **tenant** | Isolation unit; every fact table carries `tenant_id`. | Mandant |
| **macros** | `kcal`, `protein`, `carbs`, `fat`, `fiber`, `salt`. | kcal, Eiweiß, Kohlenhydrate, Fett, Ballaststoffe, Salz |
