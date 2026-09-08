# ADR 0009 — One model session per day

**Status:** accepted · **Date:** 2026-09-08

## Context

The agent turns captures (voice notes, photos, text) into day-log drafts. A run frequently covers several
days at once — after a weekend, or when the hourly worker catches up after downtime. Processing all of them
in one long conversation is convenient for the implementer but harmful for the result: the model carries
yesterday's product guesses, quantities and corrections into today ("context pollution"), the transcript of
an unrelated day competes for attention with the current one, and cost grows with every additional day in
the window. Errors produced this way look confident and are hard to trace back to their cause.

## Decision

- **Each day is drafted in its own, fresh model session.** The worker opens one Agent SDK conversation per
  day, containing only that day's captures, transcripts and (downscaled) images plus the system prompt,
  and discards it after `draft_create`.
- A run over several days executes these sessions **sequentially**, in date order. The run record
  (`agent_run`) lists the days; a new table `agent_session (run_id, date, model, prompt_version,
  input_tokens, output_tokens, cost_usd, outcome)` records each session.
- **Day assignment precedes drafting.** Captures without a `target_date` are assigned in a separate, short
  classification step (timestamp heuristics; a small model call only for ambiguous captures). The drafting
  session never sees captures of other days.
- **Shared knowledge comes through tools, not context.** The session reaches the product catalogue,
  portions and previously approved days only via `product_search`, `product_get` and `day_get`.
- The external runner (Claude Code / claude.ai over MCP) follows the same rule: `agent_run_start` locks
  exactly one day at a time for drafting, and `captures_open()` is scoped to that day. The user opens a new
  chat per day; the tools make it impossible to draft two days from one `run_id`.

## Consequences

- Drafts are small, reproducible and auditable per day; a bad draft can be re-run for one day without
  touching the others.
- Slightly more fixed overhead per run (system prompt and tool schema are sent once per day), offset by
  much smaller contexts; the budget in `agent.budget` is applied per run and reported per session.
- The `batch` mode no longer means "one context for everything" but "many isolated sessions in one run".
- Approval summaries stay per day; the run summary is a concatenation with per-day headings.
