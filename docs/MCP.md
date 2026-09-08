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

HTTP responses: missing or invalid token → `401`; token lacks the tool's scope → `403`; client outside
`allowed_cidrs` → `403`; more than `rate_limit_per_minute` calls with one token → `429`.

## Tools

| Tool | Scope | Use case | Returns |
|---|---|---|---|
| `product_search(q, limit=10)` | `read` | `SearchProducts` | candidates `{id, name, kind, tier, score, kcal_per_100}` |
| `product_get(id)` | `read` | `GetProduct` | product with portions and nutrients |
| `rules_list(scope?)` | `read` | `ListRules` | the user's own instructions (when → then) |
| `rule_upsert(when, then, name?, scope?, enabled?, priority?)` | `write` | `UpsertRule` | a rule the user just gave you, written down |
| `rule_delete(name)` | `write` | `DeleteRule` | removed |
| `product_usage(product_id, limit?)` | `read` | `GetProductUsage` | the days a product was logged on |
| `recipe_get(id)` | `read` | `GetRecipe` | recipe, ingredients, batches |
| `day_get(date)` | `read` | `GetDay` | day with meals, line items, computed macros, target band, findings |
| `days_list(from, to, status?)` | `read` | `ListDays` | compact list |
| `drafts_list()` | `read` | `ListDrafts` | days with drafts |
| `day_thread_get(date)` | `read` + `capture:read` | `GetDayContext` | the day's context: draft, thread messages, open captures, current lock holder |
| `day_message_add(date, text)` | `write` | `AddDayMessage` | message added; `follow_up` queued when applicable |
| `draft_summary(date)` | `read` | `DraftSummary` | Markdown + JSON summary |
| `report_render(name, period="14d", format="markdown")` | `read` | `ReportEngine` | rendered report (`period` like `7d`/`14d`/`30d`, or `from`/`to`) |
| `report_snapshot_create(name, period?, start?, end?, label?)` | `read` | `FreezeReport` | the frozen snapshot **and** its numbers, ready to assess |
| `report_snapshots_list(report?, limit?)` | `read` | `ListSnapshots` | snapshots, newest first |
| `report_snapshot_get(snapshot_id)` | `read` | `GetSnapshot` | one snapshot with its numbers and assessment |
| `report_assess(snapshot_id, assessment_md)` | `agent:write` | `AssessSnapshot` | the assessment attached to that moment |
| `captures_open(run_id?)` | `capture:read` | `ListCaptures` | captures with `status=new`; with `run_id` scoped to the run's locked days |
| `capture_get(id, attachment_id?)` | `capture:read` | `GetCapture` / `TranscribeCapture` / `GetAttachment` | text or transcript; images as image content; audio is transcribed lazily when a transcription provider is configured |
| `capture_mark(id, status?, target_date?, product_id?)` | `capture:write` | `UpdateCapture` | updated capture |
| `agent_run_start(mode, dates?, captures?)` | `agent:write` | `BeginAgentRun(runner="external")` | `run_id`, `locked_days`, `skipped_days` |
| `agent_run_finish(run_id, status, summary_md?)` | `agent:write` | `FinishAgentRun` | run record; releases every lock of the run |
| `draft_create(draft)` | `agent:write` | `CreateDraft` | created items; **requires a live lock held by the draft's `run_id`** |
| `draft_discard(date)` | `approve` | `DiscardDraft` | discarded count |
| `line_item_approve(line_item_id, amount?, unit_code?, consumable_id?)` | `approve` | `ApproveLineItem` | the accepted item; the rest of the day stays a draft |
| `day_approve(date, corrections[], close)` | `approve` | `ApproveDay` | approved day + warnings |
| `meal_update(meal_id, name?, time?)`, `meal_delete(meal_id)` | `write` | `UpdateMeal` / `DeleteMeal` | meal; delete fails while items remain |
| `product_propose(product_id, changes, capture_id?, source?, rationale?)` | `agent:write` | `ProposeProductChange` | proposal awaiting a person's approval; the way to act on a product capture |
| `product_update(product_id, …, source)` | `write` | `UpdateProduct` | direct product change (people and `write`-scope clients only) |
| `line_item_create / line_item_update / line_item_delete` | `write` | `AddLineItem` / `UpdateLineItem` / `DeleteLineItem` | line item |
| `product_create(...)`, `portion_create(...)` | `write` | `CreateProduct` / `AddPortion` | product / portion |
| `weight_add(date, kg)` | `write` | `AddWeight` | weight row (`source=manual`) |

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
report_render("checkup", "14d")
agent_run_finish("7f3a", status="finished", summary_md="## Drafts 2026-09-07 …")
— user reads the summary in the chat —
day_approve("2026-09-07", corrections=[], close=true)
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

Streamable HTTP (`mcp.http_enabled: true`, client inside the VPN):

```bash
victus token create --tenant alice --name "claude-code" --scopes read,capture:read,capture:write,agent:write,approve --days 90
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
| Source CIDR allow-list, enforced by the proxy and the application | Even with a token, only VPN clients reach `/mcp` |
| Write tools need a lock | Two runners cannot draft the same day |
| Tool errors are typed | `LockHeldByOtherRun`, `RunNotActive`, `ValidationFailed` map to MCP error results; never a stack trace |
| Audit log | Every write records who, what, when, diff |
