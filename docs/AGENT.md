# Agent

The agent turns captures (text, audio, photos) into **draft** day logs. It never approves anything. Two runners exist;
both use the same MCP tools, the same prompt files and the same lock table, so a day is never drafted twice.
Planned for Stage 3.

## Runners

| | Worker (in-house) | External (subscription) |
|---|---|---|
| Where | `worker` container on your server | Claude Code (`/schedule`, cron) or claude.ai with the Victus MCP connected |
| Model access | Claude Agent SDK + `providers.anthropic_api_key` | The user's Claude subscription |
| Trigger | On demand (`POST /agent/runs`, the app's **Process now** button, MCP `agent_run_start`) or optional `agent.cron` | Scheduled prompt or a chat message ("process my captures") |
| Tools | Victus MCP tools, in-process | Victus MCP over Streamable HTTP (bearer token, scopes `read`, `capture:read`, `agent:write`) |
| Summary delivery | `agent_run.summary_md`; optional push (chat plugin, e-mail) | The chat reply *is* the summary |
| Approval | User opens the app or answers in a chat that has the MCP | User answers in the same chat → `day_approve` |

## Triggers

The worker is a **queue consumer**, not a cron job. Anything that creates an `agent_run` row with
`status = queued` starts processing within seconds; the schedule is only one of three sources.

| Source | How | Notes |
|---|---|---|
| App / API | `POST /agent/runs` → `202 Accepted` with `run_id`; the web app's **Process now** button calls it and polls `GET /agent/runs/{id}` for progress and the summary | Default `mode=historical`, optional `dates`/`captures` |
| Schedule | `agent.cron` (default hourly) creates the same queued run | Set `agent.cron: null` to disable; nothing else changes |
| MCP | `agent_run_start` from an external Claude | Same lock rules; the external session drafts, the worker is not involved |

Manual and scheduled triggers never collide: both go through `agent_lock`, so a button press during a
scheduled run simply reports the days as "locked by worker" and returns immediately.

## Run protocol

```
agent_run_start(mode, dates?)          → run_id, locks acquired for the days in scope
day_thread_get(date)                   → the day's thread: existing draft, earlier messages, new captures
captures_open()                        → captures with status=new (scoped to locked days)
capture_get(id)                        → text / transcript / image resource
product_search(q) | product_get(id)    → candidates with stage and score
draft_create(run_id, date, meals[])    → draft written (schema: agent-draft.schema.json)
report_render("checkup", "14d")        → appended to the summary
agent_run_finish(run_id, summary, usage) → locks released, run recorded
```

| Step | Detail |
|---|---|
| Scope | Captures with `status = new`, grouped by `target_date`. Missing `target_date` → the agent infers it from `captured_at` and content and sets it via `capture_mark`. |
| Lock | `INSERT INTO agent_lock (tenant_id, date, runner, run_id, locked_until) … ON CONFLICT DO NOTHING`. No lock → the day is skipped silently in this run. `locked_until = now + agent.lock_ttl_minutes` (default 5 min — a single day never takes longer). |
| Session | One fresh model conversation per day (see "Session isolation"), seeded with the **day thread** (existing draft, earlier messages, new captures — ADR 0010). Discarded after the session's writes. |
| Follow-up | A new message for a day that already has a draft queues a `follow_up` run for that day; the session applies changes incrementally (`line_item_update`, `line_item_create`) instead of rebuilding the day. Messages arriving while the day is locked wait and trigger a follow-up when the lock is released. |
| Transcription | Audio captures are transcribed on upload (or lazily by `capture_get`) through `TranscriptionPort` with the tenant's `transcription.vocabulary_prompt`. |
| Images | Downscaled to 1024 px before being passed to the model; counted against `agent.budget.max_images`. |
| Matching | The agent must call `product_search` for every item and pick from the candidates; free-text items become `ad_hoc_item` rows only when no candidate scores ≥ 0.62. |
| Draft | `day_log(status='draft')` if the day is new, otherwise `line_item(is_draft=1)` on the existing day. Every item carries `confidence`, `reasoning`, `source_capture_id`, `source_kind`, `alternatives` (top 3). |
| Captures | `status = assigned` after drafting, `processed` only after approval. |
| Idempotency | `capture.content_hash` is unique per tenant; a capture that already has draft items is not drafted again. Re-running a finished run is a no-op. |
| Budget | `agent/budget.py` stops the run when `max_input_tokens`, `max_output_tokens`, `max_usd` or `max_images` is reached; remaining days stay locked until `locked_until` and are picked up next run. |
| Protocol | `agent_run` stores runner, mode, model, prompt version, tokens, cost, captures, days, summary, error. |

## Session isolation: one day, one context

**Every day is drafted in its own, fresh model session** (ADR 0009). A run may cover several days, but the
worker opens a new Agent SDK conversation per day with only that day's captures, transcripts and images in
context, and closes it after `draft_create`. Nothing from a previous day — its products, quantities,
guesses or corrections — leaks into the next one. The external runner follows the same rule: one chat per
day; the MCP tools enforce it by scoping `captures_open()` to the single locked day of the current `run_id`.

Two consequences shape the modes below:

- **Day assignment happens before drafting**, not inside it. Captures without `target_date` are assigned in a
  short, separate classification step (timestamp heuristics first, a small model call only for ambiguous
  captures), so the drafting session never has to sort a weekend's worth of notes.
- **Cross-day knowledge comes from the database, not from the context.** The drafting session reaches the
  product catalogue, portions and yesterday's approved day only through tools (`product_search`,
  `day_get`), which keeps it small and deterministic.

## Day thread: talking to a day, before, during and after processing

Each day owns a **thread** (ADR 0010): its captures (voice, photo, text — a text message typed on the day
view is a capture with `target_date`) and the agent's messages (summaries, questions, notes). You can keep
adding to it at any time, exactly like continuing a chat:

| Situation | What happens |
|---|---|
| Message before the first run | Becomes part of the day's captures; the first session sees it |
| Message **while** the day is being processed | Stays `new`; when the run releases the lock, a `follow_up` run for that day is queued automatically. The app shows the message as "waiting" |
| Message after a draft exists ("the chicken was 300 g") | Queues a `follow_up` run; the session is seeded with the current draft and the thread and applies the correction incrementally |
| Agent has a question ("chips — which pack size?") | Posted to the thread as a `question`; your reply is an ordinary message and follows the same path |
| Message on another day | Belongs to that day's thread only; ADR 0009 still holds |

Surfaces: `GET/POST /days/{date}/messages`, MCP `day_thread_get(date)` / `day_message_add(date, text)`,
the chat panel on the day view.

## Modes

| `mode` | Behaviour | Use |
|---|---|---|
| `historical` | Oldest unprocessed day first; one session per day; stops at budget | Default for the hourly worker; catches up in order |
| `batch` | All days with open captures in one run; still **one session per day**, executed sequentially | Manual "process everything from the weekend" |
| `manual` | Explicit capture IDs or date range; one session per affected day | Re-processing after a correction |
| `follow_up` | One day, seeded with its thread and current draft; incremental changes only | Queued automatically by new messages on a drafted or locked day |

CLI: `victus agent run --tenant alice --mode historical|batch|manual [--captures id,id] [--from --to]`.
`agent_run` records the list of days and one `agent_session` row per day (model, tokens, cost, outcome).

## Prompt files

| File | Purpose |
|---|---|
| `src/victus/agent/prompts/system.md` | Role, rules (never approve, always search before creating a product, flag estimates, answer in the tenant's language), tool usage order |
| `src/victus/agent/prompts/capture_to_draft.md` | Per-day instructions: portion heuristics (portion size is the riskier estimate, not nutrient density), label photos beat estimates, ask-worthy items (e.g. "chips" without quantity → low confidence + note) |
| `src/victus/agent/prompts/summary.md` | Format of the chat summary (below) |

Prompt files are versioned in the repo; `agent_run.prompt_version` records the git SHA or semantic version used.

## Summary format (chat)

```
## Drafts 2026-09-07 – 2026-09-08 (run 7f3a, 2 days, 5 captures, 0.42 USD)

### 2026-09-07 · draft · 1,383 kcal · protein 154.9 g · ⚠️ 2 estimates
| Meal | Item | Quantity | kcal | Confidence | Source |
|---|---|---|---|---|---|
| Breakfast | Skyr natural | 400 g (tub) | 252 | 0.95 | voice note 07:41 |
| Dinner | Paprika chicken (brand X) | 396 g ⚠️ | 420 | 0.62 | photo 19:02 – quantity estimated, label 106 kcal/100 g |
Alternatives: chicken natural (0.58) · chicken breast raw (0.41)

### 2026-09-08 · draft · 976 kcal (day still open)
…

**Check-up (14 d):** MA7 86.4 kg · TDEE 14 d 2,610 kcal 🟢 · required rate −0.45 kg/week

Approve? Reply "approve 2026-09-07" or give corrections (e.g. "chicken 300 g").
```

## Approval dialogue

| User says | Tool call |
|---|---|
| "approve 2026-09-07" | `day_approve(date="2026-09-07", corrections=[], close=true)` |
| "approve 09-07 but chicken 300 g and keep the day open" | `day_approve(date, corrections=[{line_item_id, quantity: 300}], close=false)` |
| "discard 2026-09-08" | `draft_discard(date="2026-09-08")` |

`ApproveDay` applies corrections, clears `is_draft`, keeps `estimated` visible, freezes `target_band_id`, sets captures to
`processed`, runs the consistency check and returns warnings (non-blocking). Every correction is an `audit_log` row.

## Draft schema

The agent's output for `draft_create` is validated against `schemas/agent-draft.schema.json`:

```json
{
  "date": "2026-09-07",
  "meals": [
    {
      "name": "Breakfast",
      "time": "07:40",
      "line_items": [
        {
          "consumable_id": 123,
          "quantity": 400, "unit_code": "g",
          "quantity_estimated": false,
          "confidence": 0.95,
          "reasoning": "Skyr is always logged as a whole 400 g tub",
          "source_capture_id": "c_01J…", "source_kind": "transcript",
          "alternatives": [{"consumable_id": 124, "score": 0.58}]
        }
      ]
    }
  ]
}
```

## Cost control

| Guard | Default | Where |
|---|---|---|
| Tokens per run | 200 k in / 20 k out | `agent.budget.*` |
| USD per run | 1.00 | `agent.budget.max_usd` |
| Images per run | 10, downscaled | `agent.budget.max_images` |
| Runs per hour | 1 per tenant (worker) | scheduler |
| Visibility | `GET /agent/runs`, report block `text_finding`, `/health` warns on cost > 5 USD/day | api, reports |
