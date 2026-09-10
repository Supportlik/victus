# ADR 0013 — `write` proposes, `approve` decides

**Status:** accepted · **Date:** 2026-09-10

## Context

ADR 0003 put a person between the agent and the statistics: the agent drafts, a person approves. The scopes were
meant to carry that rule — `approve` guards `day_approve`, `line_item_approve` and `draft_discard`. In practice the
guard only covered the front door.

A token holding `write` (the scope every agent token needs, and the one the reference MCP token has) could reach the
same end state by another route:

- `line_item_create` wrote a **non-draft** item — the very thing `line_item_approve` exists to gate. The entry
  arrived without `source_capture_id`, `confidence` or `rationale`, so it also lost the provenance a review needs.
- `line_item_delete` removed draft items one at a time, which is `draft_discard` in slow motion, and removed
  approved items outright.
- `line_item_update` changed data a person had already signed off.
- `close_day` / `reopen_day` moved a day in and out of the TDEE series — the `close` half of `day_approve`.
- `UpdateDayFlags` set `reliable`, which decides whether a day counts at all.
- `product_create`, `product_update`, `portion_create` and `product_version_create` wrote master data directly,
  although R54 says the agent never writes product values. `product_create` was even in `WORKER_TOOLS`.
- `DecideProposal` needed only `write`, so the agent could approve its own reading of a label.

The hole was found the honest way: drafting a day through MCP, the agent needed a product that did not exist,
called `product_create`, and the value went live unreviewed. Moving a draft item between meals then required
delete + create, which turned a proposal into a fact.

The second half of the problem is that there was **no working path** for a food with no product yet. `product_propose`
only proposes changes to an existing `product_id`. Doing it correctly meant either a one-off consumable with no route
into the catalogue, or writing the product and asking forgiveness.

## Decision

**Without `approve`, nothing an actor writes is a fact** (SPEC R81).

- `AddLineItem` without `approve` sets `is_draft = 1` and `origin = 'agent'`. Adding is allowed; asserting is not.
- Changing or deleting a **non-draft** item, `close_day`, `reopen_day` and setting `reliable` require `approve`
  (`require_decision`, which checks `write` first so a read-only caller still hears about `write`).
- A **draft** may be withdrawn by its author (`agent:write`), because a proposal is not yet anybody's data; plain
  `write` may not, since deleting drafts one by one is `draft_discard`.
- Every catalogue write — product, version, portion, and deciding a proposal — requires `approve`.
- A catalogue write attempted **without** `approve` becomes a proposal instead of an error. One door in the
  application layer (`create_or_propose_product`, `update_or_propose_product`, `add_or_propose_portion`) picks the
  branch, so no adapter has to remember the rule.
- A food with no product yet becomes a **`kind='new'` proposal**: its values live on a one-off consumable
  (`ad_hoc_item`), which the day can log immediately with correct macros. Approving the proposal **promotes** that
  consumable into a product in place — same id, so every line item that already points at it keeps pointing at it,
  and the food becomes searchable from that moment. Rejecting leaves the meal exactly as eaten and the catalogue
  untouched.

Deliberate exceptions, in the same spirit: `weight_add` and `body_add` stay at `write`. A weigh-in is a number the
person dictated, not an inference about it, and there is no draft state for a measurement. `rule_upsert` stays at
`write` too — a rule is the user's instruction to the agent, written down.

## Consequences

- An agent token can log, draft and propose, and cannot make anything count. The failure mode is a visible pending
  item, never a silent fact.
- The web app is unaffected: a browser session holds every scope, so a person's own edits stay immediate.
- API tokens holding only `write` now get `403` on `POST /products` and on the proposal decision endpoints. That is
  the intended answer: propose through MCP, decide in the app.
- One-off consumables gain a second life as "pending products", which keeps the day's numbers honest while the
  catalogue stays curated.
- The drafting surface has to be as wide as the deciding one, or the difference gets filled by handing out
  `approve`. Portions showed that: only *adding* one could be proposed, so a wrong unit or a duplicate row
  was cleaned up with a short-lived `approve` token instead. A proposal's `portions` list now carries one
  operation per entry (`add`, `update`, `delete`) and says what each would do to the catalogue.
- A promoted consumable changes `consumable.kind`, so the subtype row is deleted before the supertype is updated —
  the composite foreign key `(id, kind)` would otherwise refuse.
