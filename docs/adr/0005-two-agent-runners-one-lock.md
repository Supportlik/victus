# ADR 0005 — Two agent runners share one lock table

**Status:** accepted · **Date:** 2026-09-08

## Context

Processing captures with an LLM can run in two places: an in-house worker container using the Claude Agent SDK and an
API key, or an external Claude session (Claude Code, claude.ai) driven by the user's existing subscription and connected
through the Victus MCP over HTTP. Both are wanted: the worker for unattended hourly processing, the external runner for
zero-marginal-cost processing and interactive approval. Running both naively would draft the same day twice.

## Decision

- Both runners use the **same MCP tools**, the **same prompt files** (`agent/prompts/`) and the **same use cases**.
- A table `agent_lock (tenant_id, date) PRIMARY KEY, runner, run_id, locked_until` is the single coordination point.
  `agent_run_start` acquires locks with `INSERT … ON CONFLICT DO NOTHING`; a day whose lock is held is skipped silently.
- Write tools that create drafts require a `run_id` that currently holds the lock for that day; otherwise
  `LockHeldByOtherRun` is returned.
- Locks expire (`locked_until`, default **5 minutes** — one day never takes longer to draft) so a crashed runner cannot block a day for long;
  `victus agent unlock` exists for the manual case.
- Every run, from either runner, is recorded in `agent_run` with runner, mode, model, prompt version, tokens, cost and
  summary.

## Consequences

- No double drafts even when both runners are enabled and overlap.
- The external runner needs a token with `agent:write`, `capture:read` and `read`; approval additionally needs
  `approve`.
- Cost visibility is uniform: the worker reports API cost, the external runner reports usage as provided by the client
  (may be zero for subscription use).
- Skipped days are not errors; the summary lists them as "locked by <runner>".
