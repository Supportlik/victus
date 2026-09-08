# ADR 0010 — A resumable conversation thread per day

**Status:** accepted · **Date:** 2026-09-08

## Context

ADR 0009 isolates drafting to one model session per day. Real logging is not a single shot, though: the
user records a voice note at breakfast, adds a photo at lunch, and later types "the chicken was 300 g, not
400" or "forgot the apple" — possibly while a run for that day is in progress or after a draft already exists.
Those follow-ups must flow into the *same* day's context and be processed afterwards, the way a chat
continues, without re-processing the whole day from scratch and without touching other days.

## Decision

- Every `day_log` (or future date) owns a **day thread**: the ordered sequence of that day's captures (text,
  audio, image — text messages are captures of kind `text` with a `target_date`) and the agent's own
  messages (draft summaries, questions, notes). A new table `day_message (id, tenant_id, date, role
  user|agent|system, kind text|summary|question|correction, content, capture_id?, run_id?, created_at)`
  stores the agent side; captures remain the user side.
- **A drafting session for a day is seeded with the day's thread**, not only with unprocessed captures: the
  current draft (`day_get`), all previous messages of that day and the new, unprocessed captures. The session
  is still fresh and still limited to one day (ADR 0009 holds); the thread is what gives it continuity.
- **Follow-ups are processed incrementally.** A new user message for a day that already has a draft queues a
  `follow_up` run for that day. The session receives the existing draft and the new messages and applies
  changes with `line_item_update` / `line_item_create` / `draft_create` instead of rebuilding the day.
- **Messages arriving during a run are not lost.** They stay `status = new`; when the run releases the lock,
  the worker sees them and queues a follow-up for that day automatically. The web app shows the thread with
  a "processing…" marker on messages that are waiting.
- Agent questions (`open_questions` in the draft schema) are posted to the thread as `question` messages; the
  user's reply is an ordinary text capture and triggers the same follow-up path.
- Surfaces: `GET/POST /days/{date}/messages` in the API, MCP tools `day_thread_get(date)` and
  `day_message_add(date, text)`, a chat panel on the day view in the web app.

## Consequences

- The user can keep talking to a day the way one talks in a chat, before, during and after processing, and the
  agent picks up where it left — but only for that day.
- Approval semantics do not change: follow-ups produce or modify drafts; nothing counts until `day_approve`.
- One more table and two endpoints; the classification step (which day does a capture belong to) gains a
  cheap default — a message typed on the day view already carries its `target_date`.
- Threads are part of the tenant export (backup) and of the audit trail.
