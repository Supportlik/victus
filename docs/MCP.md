# MCP server

Victus exposes its use cases as MCP tools so an agent (Claude Code, claude.ai, the in-house worker) can read and
write through the same authorisation as the REST API. The server calls the **service layer directly**
([ADR 0004](adr/0004-mcp-calls-service-layer.md)). Implemented in Stage 3 (`src/victus/mcp/server.py`,
`src/victus/mcp/tools.py`).

One **tool registry** (`mcp/tools.py`) defines every tool once — name, description, JSON input schema, required
scope, handler. The MCP server registers the registry; the in-house worker turns the same registry into Anthropic
tool definitions. A behaviour change therefore lands in both runners at once.

## Transports

| Transport | Start | Auth | Use |
|---|---|---|---|
| **stdio** | `victus mcp --tenant <slug>` | Local process = trusted; tenant fixed by flag, all scopes, actor `stdio:<slug>` | Claude Code on the same machine, or via SSH forced command |
| **Streamable HTTP** | mounted at `/mcp` in the API process when `mcp.http_enabled: true` | `Authorization: Bearer vct_…` → the token's tenant and scopes; source CIDR allow-list (`mcp.allowed_cidrs`); rate limit per token (`mcp.rate_limit_per_minute`) | claude.ai connectors, Claude Code from another machine, external runner |

Neither transport should be reachable from the public internet: the API binds to `127.0.0.1`, nginx (`deploy/nginx.conf`)
proxies `/mcp` unbuffered with a long read timeout, and the Caddy configuration answers `403` to `/mcp` from outside the
VPN range. The application applies the CIDR check a second time.

HTTP responses: missing or invalid token → `401`; client outside `allowed_cidrs` → `403`; more than
`rate_limit_per_minute` calls with one token → `429`. `tools/list` returns only the tools the token's scopes allow, so
a client never sees a tool that could only fail. A tool called anyway without its scopes answers a tool error
`forbidden: scope '…' required` (HTTP `200`, `isError: true`), never a result. Over stdio every scope is held and
every tool is listed.

## Tools

The *Scope* column names every scope a tool needs: `a` + `b` means both, `a` or `b` either. It is the
same declaration the server lists tools by and checks before the handler runs (`ToolSpec.scope`); the generated
[SCOPES.md](SCOPES.md) shows every tool against every scope profile, and
[API.md → Scope profiles](API.md#scope-profiles) says which token to hand to which client.

| Tool | Scope | Use case | Returns |
|---|---|---|---|
| `product_search(q, limit=10, on?)` | `read` | `SearchProducts` | candidates `{id, name, kind, tier, score, kcal_per_100}` and matching products with `reference_unit` and `density_g_per_ml`; `on` picks the version that applied on that day (R70) |
| `product_get(id)` | `read` | `GetProduct` | product with portions, nutrients and `density_g_per_ml`, which is null unless the product carries one: without it an amount in the other unit cannot be converted (R75) |
| `rules_list(scope?)` | `read` | `ListRules` | the user's own instructions (when → then) |
| `rule_upsert(when, then, name?, scope?, enabled?, priority?)` | `write` | `UpsertRule` | a rule the user just gave you, written down |
| `rule_delete(name)` | `write` | `DeleteRule` | removed |
| `product_usage(product_id, limit?)` | `read` | `GetProductUsage` | the days a product was logged on |
| `product_versions(id)` | `read` | `ProductVersions` | every version with the days it covers |
| `body_measurements(limit?)` | `read` | `ListBodyMeasurements` | recent tape-measure sessions |
| `body_add(measured_at, waist_cm?, …)` | `write` | `AddBodyMeasurement` | one session from a note, a photo of a tape or a spoken list (R76) |
| `recipe_get(id)` | `read` | `GetRecipe` | recipe, ingredients, batches |
| `day_get(date)` | `read` | `GetDay` | day with meals, line items, computed macros, target band, findings |
| `days_list(from, to, status?)` | `read` | `ListDays` | compact list |
| `drafts_list()` | `read` | `ListDrafts` | days with drafts |
| `day_thread_get(date)` | `read` + `capture:read` | `GetDayContext` | the day's context: draft, thread messages, open captures, current lock holder |
| `day_message_add(date, text)` | `write` | `AddDayMessage` | message added; `follow_up` queued when applicable |
| `agent_message_add(run_id, date, kind, content)` | `agent:write` | `AddAgentMessage` | your own thread entry: `summary` is the day's verdict shown above its meals and replaces the previous one, `note`/`question`/`correction` accumulate |
| `draft_summary(date)` | `read` | `DraftSummary` | Markdown + JSON summary |
| `report_render(name, period="14d", format="markdown")` | `read` | `ReportEngine` | rendered report (`period` like `7d`/`14d`/`30d`, or `from`/`to`) |
| `report_snapshot_create(name, period?, start?, end?, label?)` | `read` + `write` | `FreezeReport` | the frozen snapshot **and** its numbers, ready to assess |
| `report_snapshots_list(report?, limit?)` | `read` | `ListSnapshots` | snapshots, newest first |
| `report_snapshot_get(snapshot_id)` | `read` | `GetSnapshot` | one snapshot with its numbers and assessment |
| `report_assess(snapshot_id, assessment_md)` | `agent:write` or `write` | `AssessSnapshot` | the assessment attached to that moment |
| `captures_open(date?, scope?)` | `capture:read` | `ListCaptures` | captures with `status=new`; `scope` = `day`, `product` or `all`, `date` narrows to one day |
| `capture_get(id, attachment_id?)` | `capture:read` | `GetCapture` / `TranscribeCapture` / `GetAttachment` | text or transcript; images as image content; audio is transcribed lazily when a transcription provider is configured and the token also holds `capture:write` (storing a transcript is a capture write) — otherwise the capture comes back as it stands |
| `capture_mark(id, status?, target_date?, product_id?)` | `capture:write` | `UpdateCapture` | updated capture |
| `agent_run_start(mode, dates?, captures?)` | `agent:write` | `BeginAgentRun(runner="external")` | `run_id`, `locked_days`, `skipped_days` |
| `agent_run_finish(run_id, status, summary_md?)` | `agent:write` | `FinishAgentRun` | run record; releases every lock of the run |
| `draft_create(draft)` | `agent:write` | `CreateDraft` | created items; **requires a live lock held by the draft's `run_id`** |
| `draft_discard(date)` | `write` + `approve` | `DiscardDraft` | discarded count |
| `line_item_approve(line_item_id, amount?, unit_code?, consumable_id?)` | `write` + `approve` | `ApproveLineItem` | the accepted item; the rest of the day stays a draft |
| `day_approve(date, corrections[], close)` | `write` + `approve` | `ApproveDay` | approved day + warnings |
| `meal_update(meal_id, name?, time?)`, `meal_delete(meal_id)` | `write` | `UpdateMeal` / `DeleteMeal` | meal; delete fails while items remain |
| `product_propose(product_id, changes, capture_id?, source?, rationale?)` | `agent:write` or `write` | `ProposeProductChange` | proposal awaiting a person's approval; the way to act on a product capture. `changes.portions` is a list of operations — `{op: 'add'|'update'|'delete', …}`, an entry without `op` adds — and the proposal comes back with a `portion_plan` saying what each line would do to the catalogue and what would refuse it. A person may correct the values before approving them (R84) |
| `proposal_update(proposal_id, changes, rationale?)` | `agent:write` | `AmendProposal` | your own pending proposal, corrected and still pending: `changes` merges into it, `null` withdraws a field. Refused for another token's proposal, for one a person has already corrected (`409` — file a new one instead), and once decided. Nothing is applied (R84) |
| `product_update(product_id, …, source)` | `agent:write` or `write` (+ `write` + `approve` to apply) | `update_or_propose_product` | with `approve` the values are written; without it the same call becomes a proposal (R81) |
| `product_version_create(id, valid_from, changes, rationale?)` | `agent:write` or `write` (+ `write` + `approve` to apply) | `version_or_propose_product_version` | changed values from a day on; days already logged keep their numbers (R70). Without `approve` the same call becomes a pending `kind='version'` proposal carrying `valid_from` — the honest form of “the recipe changed on this date”, which a correction to the current version is not |
| `line_item_create(date, meal, consumable_id, amount, unit_code?, …)` | `write` | `AddLineItemOnDate` | the item, in the named meal (created when the day has none of that name); **without `approve` it is added as a draft** (R81). On a date with no day log, a draft creates the day as a `draft` with `reliable` unset, as `draft_create` does; with `approve` the item would be a fact on a day nobody set up, so it answers `NotFound` saying to create the day first and set `reliable` |
| `line_item_update` | `write` (+ `approve` for approved items) | `UpdateLineItem` | changed item; `meal_id` moves it to another meal of the same day |
| `line_item_delete(line_item_id)` | `write` + (`agent:write` or `approve`): `agent:write` withdraws a draft item, a fact needs `approve` | `DeleteLineItem` | `{deleted: id}` |
| `product_create(..., portions?, capture_id?, rationale?)` | `agent:write` or `write` (+ `write` + `approve` to write it) | `create_or_propose_product` | with `approve` the product; without it a pending `new` proposal plus `log_against_consumable_id` — log the day against that id now, the person approves the catalogue entry later and it is promoted in place, keeping the item (R81) |
| `portion_create(...)` | `agent:write` or `write` (+ `write` + `approve` to apply) | `add_or_propose_portion` | portion, or a proposal carrying it |
| `portion_update(portion_id, unit_code?, label?, amount?, amount_unit?, is_default?, rationale?)` | `read` + (`agent:write` or `write`) (+ `write` + `approve` to apply) | `update_or_propose_portion` | the corrected portion, or a proposal carrying `{op: 'update', portion_id, …}` |
| `portion_delete(portion_id, reason)` | `read` + (`agent:write` or `write`) (+ `write` + `approve` to apply) | `delete_or_propose_portion` | `{deleted: id}`, or a proposal carrying `{op: 'delete', portion_id, reason}`; a portion logged items use cannot be removed |
| `weight_add(measured_at, kg)` | `write` | `AddManualWeight` | weight row (`source=manual`) |

**Scopes in one line (R81, ADR 0013): `write` proposes, `approve` decides.** A token without `approve` may read,
draft, add items (as drafts), withdraw drafts and propose catalogue changes. It cannot change or remove what
a person approved, close or reopen a day, set `reliable`, write the catalogue, or decide a proposal. Deciding needs
`write` **and** `approve`. Which scopes to grant for which client — the *assistant that proposes* recommended below,
read-only, a capture uploader, a full delegate — is described in
[API.md → Scope profiles](API.md#scope-profiles).
A person reviewing the agent's work does not only approve or reject: every drafted value and every proposed
value can be corrected first, and both readings stay on record — the day thread names a corrected item, a
proposal keeps the values as filed (R84). The agent may correct its own pending proposal with `proposal_update`
until a person has touched it.

Every write tool writes an `audit_log` row with the principal (token id or `stdio:<tenant>`). Tool errors are the
application's typed errors (`LockHeldByOtherRun`, `RunNotActive`, `NotFound`, `ValidationFailed` with the failing schema
paths) — never a stack trace.

## Typical external session

```
agent_run_start(mode="historical")           → run 7f3a, locked [2026-09-07], skipped {}
day_thread_get("2026-09-07")                 → 2 new captures, no draft yet
capture_get("cap_…")                         → transcript
product_search("skyr")                       → [{id: 123, name: "Skyr natural", tier: 2, score: 0.93}, …]
draft_create({run_id: "7f3a", date: "2026-09-07", meals: [...], source_captures: [...]})
agent_message_add("7f3a", "2026-09-07", kind="summary", content="A rest day that came in light. …")
report_render("checkup", "14d")
agent_run_finish("7f3a", status="finished", summary_md="## Drafts 2026-09-07 …")
— user reads the summary in the chat, then approves in the app —
day_approve("2026-09-07", corrections=[], close=true)   # only with a full-delegate token or over stdio
```

Keep **one chat per day** (ADR 0009): a multi-day backlog is several `agent_run_start` calls with `dates=[one day]`,
or one run whose days you draft in separate conversations.

## Configuring Claude Code

stdio, same machine:

```bash
claude mcp add victus -- victus mcp --tenant alice
```

stdio over SSH (forced command on the server):

```bash
claude mcp add victus -- ssh -q -T -o BatchMode=yes -o IdentitiesOnly=yes -i ~/.ssh/victus_mcp app@your-home-server
# authorized_keys on the server:
# command="docker compose -f /srv/victus/docker-compose.yml run --rm -T api victus mcp --tenant alice",no-pty,no-port-forwarding ssh-ed25519 AAAA…
```

Streamable HTTP (`mcp.http_enabled: true`, client inside the VPN), with the *assistant that proposes* token — it
reads, drafts and proposes, and decides nothing:

```bash
victus token create --tenant alice --name "claude-code" --scopes read,write,capture:read,capture:write,agent:write --days 90
claude mcp add --transport http victus https://victus.example.com/mcp \
  --header "Authorization: Bearer vct_xxxxxxxx.…"
```

claude.ai: add a custom connector with the same URL and bearer token (the device must be inside the VPN). A scheduled
Claude Code prompt ("process my Victus captures, one chat per day, then send me the summary") is the external runner.

## Security rules

| Rule | Why |
|---|---|
| HTTP transport off by default | Nothing listens unless deliberately enabled |
| Bearer tokens carry scopes and expire | A leaked read token cannot approve days |
| `write` proposes, `approve` decides (R81) | A leaked write token can add drafts and proposals, never a fact: approved data, day status, `reliable` and the catalogue stay out of reach |
| Source CIDR allow-list, enforced by the proxy and the application | Even with a token, only VPN clients reach `/mcp` |
| Write tools need a lock | Two runners cannot draft the same day |
| Tool errors are typed | `LockHeldByOtherRun`, `RunNotActive`, `ValidationFailed` map to MCP error results; never a stack trace |
| Audit log | Every write records who, what, when, diff |
