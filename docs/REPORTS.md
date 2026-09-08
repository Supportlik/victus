# Reports

A report is a YAML document that lists **blocks**; the engine fills each block from domain services and hands the
result to a renderer. Built-in reports live in `src/victus/reports/builtin/`, tenant reports in the database
(`POST /reports`). Definitions are validated against `schemas/report-definition.schema.json`. Planned for Stage 2.

## Definition structure

```yaml
name: <slug>                 # unique per tenant; built-ins are reserved
title: <string>
description: <string>        # optional
period:
  default: 14d               # 7d | 14d | 30d | 90d | <n>d | custom
  options: [7d, 14d, 30d, 90d, custom]
blocks:
  - type: <block type>
    id: <string>             # optional, for anchors and tests
    ...block parameters
```

Every render call takes `from`/`to` (or the default period) and the tenant settings valid at `to`.

## Block types

| `type` | Parameters | Domain service | Output |
|---|---|---|---|
| `kpi_tile` | `source` (metric path, see below), `title`, `format` | provider by path | value, unit, delta vs. previous period, traffic light |
| `band_distribution` | `macros: [kcal, protein, carbs, fat, fiber, salt]` | `band_rating.distribution` | per nutrient: days below min / between / optimal / above max, average |
| `tdee_windows` | `windows: [7,14,30]`, `show_grade: true` | `tdee.rolling_tdee`, `reliability.grade` | table window × (Ø kcal, Δ kg, TDEE, grade, coverage) |
| `trend` | `windows: [7,14,21,30]` | `trend.trend_windows` | slope kg/day and kg/week per window, actual difference |
| `forecast` | `horizons: [1m,3m,6m]`, `with_eta: true` | `forecast.forecast` | projected weight per horizon, weight at goal date, ETA to goal |
| `burndown` | `start: <date>`, `stages: from_settings` | `burndown.burndown` | planned vs. actual series, gap, required rate |
| `weekly_chart` | `weeks: 12` | `tdee.weekly_tdee` | ISO week × (Ø kg, Ø kcal, weekly TDEE) |
| `timeline` | `tdee_window: 14` | `day_macros` + `tdee.rolling_window` | one row per day: weight, moving average, intake, rolling TDEE, macros (R63) |
| `day_list` | `columns: [kcal, protein, fiber, weight, status]` | repository + `day_macros` | one row per day with flags |
| `text_finding` | `source: agent | manual`, `id` | – | Markdown slot filled by the agent summary or by hand |

### Metric paths for `kpi_tile`

| Path | Meaning | Unit |
|---|---|---|
| `weight.latest` | Last weigh-in at or before the report date | kg |
| `weight.ma7` (alias `weight.ma`) | Moving average (length from tenant settings) on the report date | kg |
| `weight.delta_week` | Change of the moving average over the last 7 days | kg |
| `tdee.rolling_7` / `tdee.rolling_14` / `tdee.rolling_30` | Rolling TDEE for that window, with quality grade | kcal |
| `tdee.reference` | The steering value: rolling 14-day TDEE, else mean of the last eight weekly values | kcal |
| `goal.rate_kg_per_week` | Required loss per week to reach the goal on time | kg/week |
| `goal.deficit_kcal` | Required daily deficit for that rate | kcal/day |
| `goal.eat_kcal` | Daily intake that yields the required deficit under the reference TDEE | kcal/day |
| `goal.to_go_kg` | Kilograms above the goal | kg |
| `kcal.average` | Average intake in the period (countable days only), rated against the corridor | kcal |
| `protein.average` / `carbs.average` / `fat.average` / `fiber.average` / `salt.average` | Period averages (countable days only), rated against the band of the last day | g |

A tile shows the delta to the same metric over the previous period of equal length unless `delta_to` names
another path. Unknown paths make the tile a `BlockError`; the rest of the report still renders.

**Engine behaviour worth knowing**

* Only *countable* days (`reliable` and `closed`) feed calorie and macro series, exactly like the predecessor's
  countable-days view. Weigh-ins after the report date are ignored so historical renders do not leak the future.
* Rolling and trend windows end on the last moving-average date at or before the report date.
* `band_distribution` rates every day against **its own** band (bands differ by training type and validity);
  `kcal` is rated against the corridor (asymmetric: below the minimum counts as "below optimum", never as a finding).
* `burndown.start` may be a date, `from_settings` (tenant `burndown_start`) or omitted (period start).

## Built-in `checkup.yaml`

This is the "am I on track?" report; it reproduces the predecessor's status output and dashboard pages.

```yaml
name: checkup
title: "Am I on track?"
description: Weight trend, TDEE, band adherence and forecast for the chosen period.
period:
  default: 14d
  options: [7d, 14d, 30d, 90d, custom]
blocks:
  - type: kpi_tile
    id: weight
    title: Weight (MA7)
    source: weight.ma7
  - type: kpi_tile
    id: rate
    title: Required rate
    source: goal.rate_kg_week
  - type: kpi_tile
    id: deficit
    title: Required deficit
    source: goal.deficit_kcal
  - type: tdee_windows
    windows: [7, 14, 30]
    show_grade: true
  - type: band_distribution
    macros: [kcal, protein, fiber, salt]
  - type: trend
    windows: [7, 14, 21, 30]
  - type: forecast
    horizons: [1m, 3m, 6m]
    with_eta: true
  - type: burndown
    start: from_settings
    stages: from_settings
  - type: day_list
    columns: [kcal, protein, fiber, weight, status]
  - type: text_finding
    id: finding
    source: agent
```

## Snapshots: a moment, assessed

A rendered report is a live view; a **snapshot** is a moment. Freezing one stores the numbers of
that period together with the date they were computed, and later data never changes them (R57).
Each snapshot carries exactly one written assessment, so the words always belong to the numbers
they were written for.

| Step | Web app | Chat / MCP |
|---|---|---|
| Freeze | "Freeze this period" on the report page | `report_snapshot_create(name, period)` returns the frozen numbers |
| Assess | the agent writes it, or you write your own note | `report_assess(snapshot_id, assessment_md)` |
| Read back | the "Moments" list, newest first, opens in place | `report_snapshots_list`, `report_snapshot_get` |

Day-level consistency checks (`source_balance_drift` and friends) are a different thing: they are
findings *about one day's data*, shown on the day view. An assessment is about the trajectory.

## As of one day

Every render carries an anchor day (`as_of`, default today). Rolling TDEE windows, trend, forecast
and the burndown end on it, and the period ends there as well, so a report is one consistent moment;
picking an earlier day shows the picture as it was then (R62).

## Renderers

| Format | Consumer | Notes |
|---|---|---|
| `json` | Angular dashboard | Typed `ReportResult` tree; charts rendered client-side with ECharts |
| `markdown` | Chat (MCP), vault export | Tables and traffic-light emoji; the only place emoji appear |
| `svg` | Optional, vault export | Ports the predecessor's dependency-free line and bar charts |

```bash
curl -H "Authorization: Bearer $VICTUS_TOKEN" \
  "https://victus.example.com/api/v1/reports/checkup/render?format=markdown&from=2026-08-25&to=2026-09-07"
```

## Creating your own report

1. Copy `checkup.yaml`, change `name` and `title`, pick blocks.
2. Validate: `victus report validate my-report.yaml`.
3. Upload: `PUT /reports/my-report` (scope `settings`) or `victus report put my-report.yaml --tenant alice`.
4. Render in the app (Reports → my-report) or via `report_render` from an agent.

Built-in names (`checkup`) cannot be overwritten; copy them under a new name.

## How the agent uses reports

The MCP tool `report_render(name, period, format="markdown")` returns the Markdown rendering. The summary prompt
calls `report_render("checkup", "14d")` after drafting so the chat summary ends with the current course. Reports never
write; a `text_finding` slot is filled by the approval use case from `agent_run.summary_md`.

## Reference values and tests

TDEE, trend, forecast and burndown numbers are pinned to the predecessor's output frozen in
`tests/fixtures/tdee_reference.json` (synthetic input series; see [TESTPLAN.md](TESTPLAN.md), *Reference values*).
A deviation is a failing test, not a reason to adjust the fixture — unless the deviation is understood and documented
in `CHANGELOG.md`.
