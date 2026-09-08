# Test fixtures

## `tdee_reference.json`

Frozen reference values for the reporting domain services (`tdee`, `trend`, `forecast`,
`burndown`, `band_rating`). See `docs/TESTPLAN.md`, section *Reference values*.

| Item | Detail |
|---|---|
| Origin | The predecessor's private report script, run once by `tests/tools/freeze_reference.py` — the functions `moving_average`, `weekly_stats`, `rolling_tdee`, `trend_per_day`, `trend_table`, `prognose_table`, `yearly_stats` and `band_verteilung` are extracted from its source and executed unchanged; the burndown formulas (inline in the predecessor) are reproduced verbatim in the tool. |
| Data | **Synthetic.** A seeded random walk (`seed` in the file): 220 days from 2025-11-20, downward trend with noise, 12 % missing weigh-ins, 15 % days without a log, some logs without protein. No real person's data. |
| Frozen | 2026-09-08 |
| Tolerances | TDEE ±1 kcal · weights and moving average ±0.01 kg · regression slope ±0.0005 kg/day · forecast ±0.01 kg · burndown ±0.01 kg and ±0.001 kg/week |
| Re-freeze | `VICTUS_LEGACY_SCRIPTS=<dir with build_report.py and status.py> uv run python tests/tools/freeze_reference.py`. Only when a formula changes **on purpose**; a failing comparison is a finding to investigate, never a reason to regenerate. |

The loader lives in `tests/unit/domain/conftest.py` (`ref` fixture). Hand-calculated
mini examples sit next to every reference comparison so the formulas stay readable
without the fixture.
