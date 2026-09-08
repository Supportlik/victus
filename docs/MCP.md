# MCP server

Victus exposes its use cases as MCP tools so an agent (Claude Code, claude.ai, the in-house worker) can read and
write through the same authorisation as the REST API. The server calls the **service layer directly**
([ADR 0004](adr/0004-mcp-calls-service-layer.md)). Planned for Stage 3.

## Transports

| Transport | Start | Auth | Use |
|---|---|---|---|
| **stdio** | `victus mcp --tenant <slug>` | Local process = trusted; tenant fixed by flag | Claude Code on the same machine, or via SSH forced command |
| **Streamable HTTP** | mounted at `/mcp` in the API process when `mcp.http_enabled: true` | `Authorization: Bearer vct_…` with scopes; source CIDR allow-list (`mcp.allowed_cidrs`); rate limit per token | claude.ai connectors, Claude Code from another machine, external runner |

Neither transport should be reachable from the public internet: the API binds to `127.0.0.1` and the reverse proxy
serves the VPN interface only.

## Tools

| Tool | Scope | Use case | Returns |
|---|---|---|---|
| `product_search(q, limit=10)` | `read` | `SearchProducts` | candidates `{id, name, kind, stage, score, kcal_per_100}` |
| `product_get(id)` | `read` | | product with portions and nutrients |
| `recipe_get(id)` | `read` | | recipe, ingredients, batches |
| `day_get(date)` | `read` | | day with meals, line items, computed macros, target band, findings |
| `days_list(from, to, status?)` | `read` | | compact list |
| `drafts_list()` | `read` | | days with drafts |
| `day_thread_get(date)` | `read` | | the day's thread: draft, earlier messages, new captures |
| `day_message_add(date, text)` | `capture:write` | | message added; `follow_up` queued when applicable |
| `draft_summary(date)` | `read` | | Markdown + JSON summary |
| `report_render(name, period, format="markdown")` | `read` | `RenderReport` | rendered report |
| `captures_open()` | `capture:read` | | captures with `status=new` |
| `capture_get(id)` | `capture:read` | | text, transcript, image (as MCP resource) |
| `capture_mark(id, status, target_date?)` | `capture:write` | | updated capture |
| `agent_run_start(mode, dates?)` | `agent:write` | `StartAgentRun` | `run_id`, locked days |
| `agent_run_finish(run_id, summary, usage)` | `agent:write` | `FinishAgentRun` | run record |
| `draft_create(run_id, date, meals[])` | `agent:write` | `CreateDraft` | created items; **requires a live lock held by `run_id`** |
| `draft_discard(date)` | `approve` | | discarded count |
| `day_approve(date, corrections[], close)` | `approve` | `ApproveDay` | approved day + warnings |
| `line_item_create / line_item_update / line_item_delete` | `write` | | line item |
| `product_create(...)`, `portion_create(...)` | `write` | | product / portion |
| `weight_add(date, kg)` | `write` | | weight row (`source=manual`) |

Every write tool writes an `audit_log` row with the principal (token id or `stdio:<tenant>`).

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

Streamable HTTP:

```bash
victus token create --tenant alice --name "claude-code" --scopes read,capture:read,agent:write,approve --days 90
claude mcp add --transport http victus https://victus.example.com/mcp \
  --header "Authorization: Bearer vct_xxxxxxxx.…"
```

claude.ai: add a custom connector with the same URL and bearer token (the device must be inside the VPN).

## Security rules

| Rule | Why |
|---|---|
| HTTP transport off by default | Nothing listens unless deliberately enabled |
| Bearer tokens carry scopes and expire | A leaked read token cannot approve days |
| Source CIDR allow-list | Even with a token, only VPN clients reach `/mcp` |
| Write tools need a lock | Two runners cannot draft the same day |
| Tool errors are typed | `LockHeldByOtherRun`, `TenantMismatch`, `ValidationError` map to MCP error codes; never a stack trace |
| Audit log | Every write records who, what, when, diff |
