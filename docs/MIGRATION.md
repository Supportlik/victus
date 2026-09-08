# Migration from a Markdown vault

`victus import vault` moves Markdown-based tracking (an Obsidian vault with the day-log format described below) into
Victus. It is repeatable, reports what it could not resolve, and never deletes anything in the vault. Planned for
Stage 1.

## Command

```bash
victus import vault --path /path/to/vault --tenant alice --dry-run --report import-report.md
victus import vault --path /path/to/vault --tenant alice --report import-report.md
```

| Option | Meaning |
|---|---|
| `--path` | Vault root |
| `--tenant` | Target tenant slug (must exist) |
| `--dry-run` | Parse, match, compute the report; write nothing |
| `--report` | Markdown report path |
| `--only` | Restrict to `target-bands`, `products`, `recipes`, `days`, `weight` |
| `--replace-day YYYY-MM-DD` | Delete and re-import one day (its meals and line items) |
| `--from / --to` | Date range for day logs |
| `--layout` | YAML file mapping the vault's folders and files (defaults below) |

### Source layout (`--layout`, defaults)

| Key | Default (relative to `--path`) | Content |
|---|---|---|
| `days_dir` | `nutrition/diary/` | `YYYY-MM/YYYY-MM-DD.md` day logs |
| `foods_file` | `nutrition/foods.md` | Markdown tables of products with nutrients per 100 g/ml |
| `recipes_dir` | `nutrition/recipes/` | One Markdown file per recipe |
| `weight_csv` | `nutrition/weight/raw.csv` | `timestamp;weight_kg` |
| `settings_json` | `nutrition/config.json` | Goal, corridor, target bands of the predecessor scripts |

The importer was written against a German-language vault; the parser accepts German number formats and headings
(see [GLOSSARY.md](GLOSSARY.md), column *German source term*).

## Day-log format the parser understands

| Element | Expectation |
|---|---|
| Frontmatter | `date`, `reliable` (`belastbar`), `open` (`offen`), `training`, `source`, and the macro block `kcal`, `protein`, `carbs`, `fat`, `fiber`, `salt` (German keys accepted). Decimal point. |
| Meals | `###` headings; each followed by a table with 7 or 8 columns (`Item | Quantity | kcal | P | C | F | Fiber | [Salt]`) and a bold total row |
| Wikilinks | `[[target\|Display]]` with escaped pipe; the display text is the item name |
| Balance section | `## … Tagesbilanz` table; used as the cross-check (`source_*` columns), not as the source of truth |
| Late additions | Meals may appear **after** the balance section and are still counted |
| Numbers | `1.056` = 1056, `150,5` = 150.5, `~`/`≈`/`ca.`/`⚠️` mark estimates |

## Order and targets

| Step | Source | Target | Notes |
|---|---|---|---|
| 1 | `settings_json` | `tenant_settings` v1, `target_band` rows | Contradicting definitions (e.g. several salt bands) are listed as review items |
| 2 | `foods_file` | `category`, `consumable`/`product`, `portion` | Salt and portion weights are parsed from free text; `external_ref = <line number>`; `verified = 1` when the source cell marks a label or manufacturer source |
| 3 | `recipes_dir` | `recipe`, `recipe_ingredient`, one `recipe_batch` "unknown batch" | Per-100 g values come from the recipe's nutrient table |
| 4 | `days_dir` | `day_log`, `meal`, `line_item` | Frontmatter macros stored as `source_*` for the cross-check; `status` from the open flag; `created_by = import` |
| 5 | `weight_csv` | `weight_entry(source='import')` | Multiple weigh-ins per day are kept; reports average per day |

## Matching

Line items are matched to products in three stages ([ARCHITECTURE.md](ARCHITECTURE.md), `matching.py`):

| Stage | Rule | Confidence |
|---|---|---|
| 1 | Exact match on normalised name **including** parentheses | 1.0 |
| 2 | Exact match on the short form (without parentheses) — only if unique | 0.9 |
| 3 | Fuzzy match with coverage ≥ 0.62 (recipes ≥ 0.75) | score |
| – | No match → `ad_hoc_item` with nutrients from the log row, listed on the **review list** | 0 |

Known traps that are regression tests: "potato (raw)" vs. "(cooked)" must not collide; an ingredient name that is a
substring of a recipe name must not match the recipe.

## The import report

```
# Import report – 2026-09-15 21:04

| Source | Read | Written | Skipped |
|---|---|---|---|
| Products | 581 rows | 380 products, 182 portions | 201 non-data rows |
| Recipes | 33 | 33 (+33 batches) | – |
| Day logs | 134 | 134 days, 340 meals, 1 051 line items | – |
| Weight | 484 | 484 | 0 duplicates |

## Matching
Stage 1: 612 · Stage 2: 96 · Stage 3: 40 · unmatched: 303  → match rate 71.2 %

## Round-trip gate (≤ 3 % kcal deviation frontmatter ↔ computed)
Passed: 81 / 134 · not assessable: 5 · failed: 48  → see review list

## Review list
| Day | Item (raw) | Top candidates (score) | Deviation |
| 2026-06-12 | paprika chicken ~240 g | Paprika chicken brand X (0.58), chicken breast (0.41) | +112 kcal |
…
```

(Numbers are illustrative.) The gate must be **at least** the baseline measured in the dry run; a lower result blocks
the real import unless `--force` is given.

## Working the review list

1. Open *Products → Review list* in the app (or `POST /products/match` per item).
2. Pick the right product or create it (label photo beats estimate). `ReassignLineItem` keeps the frozen quantity and
   propagates the product's nutrients.
3. The day's computed macros update immediately; the round-trip check re-runs on the next report render.
4. Items that were genuinely one-off (restaurant) stay `ad_hoc_item` — mark them *reviewed* so they leave the list.

## Re-importing a day

```bash
victus import vault --path … --tenant alice --replace-day 2026-08-19 --report re-19.md
```

The day is deleted (meals, line items) and re-read; products are untouched. Use this after fixing the Markdown source.

## Running in parallel with the vault

Until Stage 3 is live, the vault stays the capture path and Victus is a second reader:

| Period | Vault | Victus |
|---|---|---|
| Stage 1–2 | Still written by the existing tooling | Re-import weekly (`--from` last import date); reports compare |
| Stage 3 | Captures go to Victus; the vault receives an optional Markdown export | Source of truth |
| After | Vault folder becomes a read-only archive | – |

Nothing in the vault is deleted at any point.
