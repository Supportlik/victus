# Agent

The agent turns captures (text, audio, photos) into **draft** day logs. It never approves anything. Two runners exist;
both use the same tool registry, the same prompt files and the same lock table, so a day is never drafted twice.
Implemented in Stage 3 (`src/victus/agent/`, `src/victus/mcp/tools.py`, `src/victus/application/use_cases/agent.py`).

## Runners

| | Worker (in-house) | External (subscription) |
|---|---|---|
| Where | `worker` container on your server (`victus worker`) | Claude Code (`/schedule`, cron) or claude.ai with the Victus MCP connected |
| Model access | Anthropic SDK + `providers.anthropic_api_key` | The user's Claude subscription |
| Trigger | On demand (`POST /agent/runs`, the app's **Process now** button) or optional `agent.cron` | Scheduled prompt or a chat message ("process my captures") |
| Tools | The Victus tool registry, in-process | The same registry over MCP (stdio or Streamable HTTP; scopes `read`, `capture:read`, `capture:write`, `agent:write`) |
| Summary delivery | `agent_run.summary_md`, shown on the Agent page and after **Process now** | The chat reply *is* the summary |
| Approval | User opens the app or answers in a chat that has the MCP | User answers in the same chat → `day_approve` |

## Triggers

The worker is a **queue consumer**, not a cron job. Anything that creates an `agent_run` row with
`status = queued` is picked up within `agent.poll_seconds` (default 5 s); the schedule is only one of three sources.

| Source | How | Notes |
|---|---|---|
| App / API | `POST /agent/runs` → `202 Accepted` with the run; the web app's **Process now** button calls it and polls `GET /agent/runs/{id}` for progress and the summary | Default `mode=historical`, optional `captures`/`from`/`to` |
| Schedule | `agent.cron` (default hourly) creates the same queued run when `agent.enabled: true` | Set `agent.cron: null` to disable; nothing else changes |
| MCP | `agent_run_start` from an external Claude | Same lock rules; the external session drafts, the worker is not involved |
| Day thread | A message or capture on a day that already has a draft or is locked queues a `follow_up` run automatically | One queued follow-up per day; further messages merge into it |

Manual and scheduled triggers never collide: both go through `agent_lock`, so a button press during a
scheduled run simply reports the days as "locked by worker" and returns immediately.

## Run protocol

```
agent_run_start(mode, dates?)              → run_id, locked days, skipped days (held elsewhere)
day_thread_get(date)                       → the day's context: existing draft, thread messages, open captures
captures_open(run_id?)                     → captures with status=new (scoped to the run's locked days)
capture_get(id)                            → text / transcript / image content
product_search(q) | product_get(id)        → candidates with tier and score
draft_create(draft)                        → draft written (schema: agent-draft.schema.json; run_id + date inside)
report_render("checkup", "14d")            → appended to the summary
agent_run_finish(run_id, status, summary)  → locks released, run recorded
```

| Step | Detail |
|---|---|
| Scope | Captures with `status = new`, grouped by `target_date`. A capture without `target_date` is not drafted; set the day in the app ("Set day") or via `capture_mark`. |
| Lock | `INSERT INTO agent_lock (tenant_id, date, runner, run_id, locked_until) … ON CONFLICT DO NOTHING`. No lock → the day is skipped in this run and reported as skipped. `locked_until = now + agent.lock_ttl_minutes` (default 5 min — a single day never takes longer); the runner extends the lock between long turns. |
| Session | One fresh model conversation per day (see "Session isolation"), seeded with the **day thread** (existing draft, earlier messages, new captures — ADR 0010). Discarded after the session's writes. |
| Follow-up | A new message for a day that already has a draft queues a `follow_up` run for that day; the session applies changes incrementally (`line_item_update`, `line_item_create`) instead of rebuilding the day. Messages arriving while the day is locked queue the follow-up right away; it starts when the lock is released. |
| Transcription | Audio captures are transcribed on upload (when `providers.openai_api_key` is set) or lazily before the session / by `capture_get`, through `TranscriptionPort` with the tenant's `transcription.language` and `vocabulary_prompt`. A failed transcription marks the capture `failed`; **Re-transcribe** in the app retries. |
| Images | Downscaled to 1024 px before being passed to the model; counted against `agent.budget.max_images_per_run`. |
| Matching | The agent must call `product_search` for every item and pick from the candidates; free-text items become `ad_hoc_item` rows (with the nutrition values the agent states per 100 g) only when no candidate scores ≥ 0.62. |
| New products | A food with no catalogue entry and known label values goes through `product_create`, which without `approve` files a `kind='new'` proposal and returns `log_against_consumable_id` for the draft. Approving it promotes that one-off into the product, keeping every item logged against it (R81, ADR 0013). |
| Draft | `day_log(status='draft', created_by_kind='agent')` if the day is new, otherwise `line_item(is_draft=1)` on the existing day (a closed day must be reopened first). Every item carries `confidence`, `rationale`, `source_capture_id`, `source_kind`, `alternatives` (top 3), `raw_text`. |
| Captures | `status = assigned` after drafting, `processed` only after approval. |
| Idempotency | `capture.content_hash` is unique per tenant; a capture that already has draft items is not drafted again. Finishing a finished run is a no-op. |
| Budget | `agent/budget.py` stops the run (`status = budget_exceeded`) when `max_input_tokens`, `max_output_tokens`, `max_usd_per_run` or `max_images_per_run` is reached; remaining days are released and picked up by the next run. |
| Protocol | `agent_run` stores runner, mode, model, prompt version, tokens, cost, captures, days, summary, error; `agent_session` one row per day. |

## Session isolation: one day, one context

**Every day is drafted in its own, fresh model session** (ADR 0009). A run may cover several days, but the
worker opens a new conversation per day with only that day's captures, transcripts and images in
context, and closes it after `draft_create`. Nothing from a previous day — its products, quantities,
guesses or corrections — leaks into the next one. The external runner follows the same rule: one chat per
day; the MCP tools enforce it by scoping `captures_open()` to the days locked by the current `run_id`.

Two consequences shape the modes below:

- **Day assignment happens before drafting**, not inside it. Captures without `target_date` are assigned by the
  user (app or `capture_mark`) — the drafting session never has to sort a weekend's worth of notes.
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
| Message **while** the day is being processed | Stays `new`; a `follow_up` run for that day is queued and starts when the lock is released. The app shows the message as "waiting for the agent" |
| Message after a draft exists ("the chicken was 300 g") | Queues a `follow_up` run; the session is seeded with the current draft and the thread and applies the correction incrementally |
| Agent has a question ("chips — which pack size?") | Posted to the thread as a `question`; your reply is an ordinary message and follows the same path |
| Message on another day | Belongs to that day's thread only; ADR 0009 still holds |

Surfaces: `GET/POST /days/{date}/messages`, MCP `day_thread_get(date)` / `day_message_add(date, text)`,
the chat panel on the day view (agent messages are tagged `summary`, `question`, `note`; your captures show
"waiting for the agent" or "in draft").

## The user's rules

Whatever the user wrote down as a rule (R61) is handed to the session as a "The user's own rules"
section: `when` → `then`, most important first, filtered to the session's scope (`days` or
`products`). Rules win over the agent's own judgement, which is the point: "for bread rolls take the
bakery's own site" is knowledge the model cannot derive. Rules are managed in the app under Settings
or in a chat with `rule_upsert` / `rule_delete`.

## Product captures

A capture uploaded with `product_id` (the product page's "Label photos & notes", or `POST /captures` with
`product_id`) is about one product, never about a day. It is processed in its own short step, outside any
day session: `captures_open(scope="product")` → `capture_get` (image or transcript) → `product_get` →
`product_update` with the legible label values and `source = "label photo, capture <id>"` (plus
`portion_create` when the label states a portion) → `capture_mark(processed)`. Values that cannot be read
are left untouched and the capture is marked `failed` with a note in the summary. Corrected nutrients
propagate to every logged quantity of that product by design; `verified` stays false until a person
confirms the product in the review list.

## Modes

| `mode` | Behaviour | Use |
|---|---|---|
| `historical` | Oldest unprocessed day first; one session per day; stops at budget | Default for the hourly worker and the **Process now** button; catches up in order |
| `batch` | All days with open captures in one run; still **one session per day**, executed sequentially | Manual "process everything from the weekend" |
| `manual` | Explicit capture IDs or date range; one session per affected day | Re-processing after a correction |
| `follow_up` | One day, seeded with its thread and current draft; incremental changes only | Queued automatically by new messages on a drafted or locked day |
| `assess` | Judges the frozen reports waiting for an assessment, one short session each; locks no day and writes no draft. The frozen figures come from the prompt, never fetched fresh, so the judgement is about that moment (R72) | The **Assess now** button, and the hand-off to the user's Claude when no key is configured |

CLI: `victus agent run --tenant alice [--mode historical|batch|manual|follow_up|assess] [--captures id,id] [--from YYYY-MM-DD --to YYYY-MM-DD]`
queues a run and processes it in-process, then prints the summary. `victus agent runs --tenant alice` lists runs;
`victus agent unlock --tenant alice --date 2026-09-07` drops a stuck lock.

## Worker

`victus worker` (the `worker` compose service) loops every `agent.poll_seconds`:

1. For every active tenant, claim queued runs oldest first and process them (`BeginAgentRun` → one session per
   locked day → `FinishAgentRun`).
2. If `agent.enabled` and `agent.cron` match the current minute, queue a `historical` run per tenant.
3. Touch the heartbeat file (`/tmp/victus-worker.alive`, override with `VICTUS_WORKER_HEARTBEAT`) — the compose
   healthcheck marks the container unhealthy when the file is older than 15 minutes.

`victus worker --once` performs a single tick (used in tests and for cron-driven hosts). Without
`providers.anthropic_api_key` a claimed run finishes as `failed` with a clear error — the external runner is
unaffected. The worker stops cleanly on `SIGTERM`; a run interrupted mid-day frees its day when the lock expires.

## Model calls

The in-house runner uses the Anthropic Python SDK with a manual tool loop (no beta dependency):

| Setting | Default | Notes |
|---|---|---|
| `agent.model` | `claude-opus-5` | Any current Anthropic model id; prices per model in `agent.pricing` |
| Thinking | adaptive | `thinking: {type: "adaptive"}`; depth via `agent.effort` (`medium`) |
| `agent.max_tokens` | 16000 | Per turn |
| `agent.fallbacks` | `true` | Server-side refusal fallbacks (beta `server-side-fallback-2026-07-01`, `fallbacks: "default"`). When a turn still ends with `stop_reason = refusal`, the day session ends with outcome `refused` and the day stays undrafted |
| `agent.max_turns_per_day` | 40 | Guard against tool loops; outcome `stuck` |
| Tool results | one user message per assistant turn | All `tool_result` blocks of a turn are returned together; failed tools return `is_error: true` with the typed error message |
| Cost | `agent.pricing` | `input_tokens × input_per_mtok + output_tokens × output_per_mtok`, booked per session and summed per run |

## Prompt files

| File | Purpose |
|---|---|
| `src/victus/agent/prompts/system.md` | Role, rules (never approve, always search before creating a product, flag estimates, answer in the tenant's language), tool usage order |
| `src/victus/agent/prompts/capture_to_draft.md` | Per-day instructions: portion heuristics (portion size is the riskier estimate, not nutrient density), label photos beat estimates, ask-worthy items (e.g. "chips" without quantity → low confidence + open question) |
| `src/victus/agent/prompts/summary.md` | Format of the chat summary (below) |

Prompt files are versioned in the repo; `agent_run.prompt_version` and `agent_session.prompt_version` record the
first 12 hex digits of the SHA-256 over the three files, so a changed prompt is visible in every run record.

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

The same per-day section is posted to the day thread as an agent `summary` message.

## Approval dialogue

| User says | Tool call |
|---|---|
| "approve 2026-09-07" | `day_approve(date="2026-09-07", corrections=[], close=true)` |
| "approve 09-07 but chicken 300 g and keep the day open" | `day_approve(date, corrections=[{line_item_id, amount: 300}], close=false)` |
| "discard 2026-09-08" | `draft_discard(date="2026-09-08")` |

`ApproveDay` applies corrections, clears `is_draft`, keeps `estimated` visible, freezes `target_band_id`, sets captures to
`processed`, runs the consistency check and returns warnings (non-blocking). Every correction is an `audit_log` row.

## Draft schema

The agent's output for `draft_create` is validated against `schemas/agent-draft.schema.json` (`CreateDraft` rejects
anything else with a `422` listing the failing paths):

```json
{
  "run_id": "run_01J…",
  "date": "2026-09-07",
  "source_captures": ["cap_01J…"],
  "meals": [
    {
      "name": "Breakfast",
      "time": "07:40",
      "line_items": [
        {
          "raw_text": "a whole tub of skyr",
          "candidates": [{"consumable_id": 123, "name": "Skyr natural", "score": 0.93, "tier": 2}],
          "chosen_consumable_id": 123,
          "quantity": 400, "unit_code": "g",
          "estimated": false, "quantity_estimated": false,
          "confidence": 0.95,
          "rationale": "Skyr is always logged as a whole 400 g tub",
          "source_kind": "transcript", "source_capture_id": "cap_01J…"
        }
      ]
    }
  ],
  "training": "rest",
  "notes": ["Protein already at the optimum."],
  "open_questions": []
}
```

`chosen_consumable_id: null` plus `one_off_nutrition_per_100` creates an `ad_hoc_item`; `notes` become `note`
messages and `open_questions` become `question` messages in the day thread.

## Cost control

| Guard | Default | Where |
|---|---|---|
| Tokens per run | 400 k in / 40 k out | `agent.budget.max_input_tokens` / `max_output_tokens` |
| USD per run | 2.00 | `agent.budget.max_usd_per_run` |
| Images per run | 12, downscaled to 1024 px | `agent.budget.max_images_per_run` |
| Turns per day | 40 | `agent.max_turns_per_day` |
| Runs per hour | 1 per tenant from the schedule; on-demand runs unlimited but serialised by the locks | worker |
| Visibility | Agent page (runs, sessions, cost), `GET /agent/runs`, `victus agent runs` | api, web, cli |
