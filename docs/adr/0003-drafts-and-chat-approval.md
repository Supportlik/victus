# ADR 0003 — Agent writes drafts; approval via chat summary or web app

**Status:** accepted · **Date:** 2026-09-08

## Context

The agent reads captures (voice notes, photos, text) and proposes day-log entries. The predecessor workflow never
skipped the human confirmation step: a wrongly logged day counts into TDEE and reports and silently distorts them.
At the same time, the owner does not want to open a form for every meal; confirming a compact summary in the chat
they already use is the preferred interaction.

## Decision

- The agent may only create **drafts**: `day_log.status = 'draft'` for new days, `line_item.is_draft = 1` for items on
  existing days. Drafts are excluded from every statistic.
- Every draft item carries `confidence`, `reasoning`, `source_capture_id`, `source_kind` and up to three
  `alternatives`; estimates are flagged and stay flagged after approval.
- Approval is one use case, `ApproveDay(date, corrections, close)`, reachable from the web app and from the MCP tool
  `day_approve`. It applies corrections, clears draft flags, freezes the target band, marks captures processed and
  writes an `audit_log` row per change.
- The agent ends every run with a Markdown **summary** (per day: meals, items, quantities, confidence, ⚠️ marks,
  alternatives; plus the current check-up). In the external runner the chat reply is that summary; the user answers
  "approve <date>" or gives corrections, and the same tool is called.

## Consequences

- No unattended write ever reaches the statistics; the failure mode becomes "draft not yet approved", which is visible.
- Two approval surfaces (app, chat) but one code path.
- Drafts accumulate if the user does not approve; the app shows a counter and the worker stops drafting a day that
  already has drafts.
- `reliable` keeps its meaning — the *user's* wholesale estimate — independent of how many items the agent estimated.
