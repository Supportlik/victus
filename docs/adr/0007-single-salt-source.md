# ADR 0007 — Salt targets live only in `target_band`

**Status:** accepted · **Date:** 2026-09-08

## Context

The predecessor held salt targets in three places with three different values: a macro-band block in a config file,
a separate "salt by training day" block in the same file, and a hard-coded table in the import script. Reports used one,
the importer another, and the human-readable spec a third. Salt is also the one nutrient whose target legitimately
depends on the day's training type (sweat loss), which invites ad-hoc overrides.

## Decision

- All nutrient bands, including salt, live in the table `target_band`: one row per complete profile, per
  `training_type` (`rest`, `strength`, `martial_arts`), versioned by `valid_from`/`valid_to`.
- Tenant settings **must not** contain salt keys; the settings schema rejects them.
- A `day_log` freezes its `target_band_id` when it is closed, so later band changes do not rewrite history.
- The vault importer seeds target bands from the predecessor configuration and lists any contradiction it finds as a
  review item for the operator to resolve once.

## Consequences

- One query answers "what was the salt target on that day"; reports, the agent and the UI cannot disagree.
- Changing a target is a new version, not an edit; old days keep their evaluation.
- Slightly more ceremony to change a single number (new band version) — accepted, because it is exactly the
  history-preservation the predecessor lacked.
