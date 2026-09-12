# Configuration reference

Victus has two configuration layers:

| Layer | Where | Changes how often | Validated by |
|---|---|---|---|
| **Server configuration** | `victus.yaml` + environment variables `VICTUS_*` | At deployment | `schemas/victus-server-config.schema.json` |
| **Tenant settings** | table `tenant_settings` (versioned JSON), edited in the web app or via `PUT /settings` | Whenever goals change | `schemas/tenant-settings.schema.json` |

Precedence for server configuration: **environment > `victus.yaml` > built-in defaults**. Environment keys are the YAML
path in upper snake case with `VICTUS_` prefix and `__` for nesting, e.g. `database.url` → `VICTUS_DATABASE__URL`.

## Server configuration (`victus.yaml`)

### `server`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `server.host` | str | no | `127.0.0.1` | Bind address of the API process |
| `server.port` | int | no | `8090` | Bind port |
| `server.base_url` | str | yes | – | Public URL, e.g. `https://victus.example.com`; used for links and CORS |
| `server.log_level` | enum | no | `info` | `debug` / `info` / `warning` |
| `server.log_format` | enum | no | `json` | `json` / `text` |

### `database`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `database.url` | str | no | `sqlite:///data/victus.db` | SQLAlchemy URL. SQLite gets WAL mode and `PRAGMA foreign_keys=ON` on every connection; use `postgresql+psycopg://…` for PostgreSQL |
| `database.echo` | bool | no | `false` | Log SQL statements |
| `database.pool_size` | int | no | `5` | Connection pool (PostgreSQL only) |

### `storage`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `storage.backend` | enum | no | `fs` | `fs` (filesystem). S3-compatible backend is planned. |
| `storage.path` | str | no | `data/blobs` | Root for attachments, laid out as `<tenant>/<yyyy>/<mm>/<sha256>` |
| `storage.max_upload_mb` | int | no | `25` | Upload limit per capture |

### `auth`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `auth.rp_id` | str | **yes** | – | WebAuthn relying-party ID, e.g. `victus.example.com`. **Pinned at the first passkey registration; the server refuses to start with a different value** (see [ADR 0006](adr/0006-rp-id-pinned.md)). |
| `auth.origin` | str | **yes** | – | Expected origin, e.g. `https://victus.example.com` |
| `auth.rp_name` | str | no | `Victus` | Display name shown by the authenticator |
| `auth.session_ttl_days` | int | no | `30` | Rolling session lifetime |
| `auth.token_max_days` | int | no | `365` | Upper bound for API-token expiry |
| `auth.invite_only` | bool | no | `true` | New users only via invitation |

### `providers`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `providers.openai_api_key` | secret | for transcription | – | Used by the OpenAI transcription adapter |
| `providers.anthropic_api_key` | secret | for the worker runner | – | Used by the in-house agent worker; not needed when only the external runner is used |
| `providers.scale_sync.username` / `.password` | secret | for scale sync | – | Credentials of the scale vendor's cloud account |

### `transcription`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `transcription.provider` | enum | no | `openai` | `openai` / `null` (disabled) |
| `transcription.model` | str | no | `gpt-4o-transcribe` | Provider model name |
| `transcription.max_file_mb` | int | no | `25` | Files above this are rejected (`TranscriptionError`) |
| `transcription.ffmpeg_path` | str | no | `ffmpeg` | Binary used to convert `.oga`/`.opus`/`.webm` to MP3 before upload; if it is missing, those formats fail with a clear error |

### `agent`

Env prefix `VICTUS_AGENT__…` (nested keys with `__`, e.g. `VICTUS_AGENT__BUDGET__MAX_USD_PER_RUN`).

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `agent.enabled` | bool | no | `false` | Let the worker create **scheduled** runs (`agent.cron`). On-demand runs (`POST /agent/runs`, the app's **Process now**, MCP `agent_run_start`) work regardless — the worker only needs to be running |
| `agent.cron` | str \| null | no | `0 * * * *` | Worker schedule; `null` disables it — runs are then started only on demand |
| `agent.poll_seconds` | int | no | `5` | How often the worker looks for queued runs |
| `agent.lock_ttl_minutes` | int | no | `5` | `agent_lock.locked_until` horizon; a single day is drafted well within this, so a crashed run frees its day quickly. The runner extends the lock between long turns |
| `agent.model` | str | no | `claude-opus-5` | Model for the worker runner (Anthropic model id, no date suffix) |
| `agent.effort` | enum | no | `medium` | `low` / `medium` / `high` / `xhigh` / `max`; sent as `output_config.effort`. Drafting is routine work — raise it only if drafts miss items |
| `agent.max_tokens` | int | no | `16000` | `max_tokens` per model turn |
| `agent.fallbacks` | bool | no | `true` | Server-side refusal fallbacks (beta header `server-side-fallback-2026-07-01`, `fallbacks: "default"`). With `false` a refused turn ends the day session with outcome `refused` |
| `agent.max_turns_per_day` | int | no | `40` | Model turns per day session; beyond this the session is abandoned as stuck |
| `agent.budget.max_input_tokens` | int | no | `400000` | Per run, summed over all day sessions |
| `agent.budget.max_output_tokens` | int | no | `40000` | Per run |
| `agent.budget.max_usd_per_run` | float | no | `2.0` | Per run; the run stops gracefully (`budget_exceeded`) when reached, remaining days are picked up by the next run |
| `agent.budget.max_images_per_run` | int | no | `12` | Images per run, downscaled to 1024 px before they reach the model |
| `agent.pricing.<model>.input_per_mtok` / `.output_per_mtok` | float | no | opus-5 5/25, sonnet-5 2/10, haiku-4-5 1/5 | USD per million tokens used to book `agent_run.cost_usd` / `agent_session.cost_usd`. Unknown model ids fall back to the opus-5 rates |

### `events`

The push channel behind `GET /api/v1/events` (R83). It costs one `MAX(audit_log.id)` per
connected client per `poll_seconds`; with it the web app stops polling four endpoints a
minute and the page a person is looking at stops showing stale data.

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `events.enabled` | bool | no | `true` | Serve the stream. With `false` the endpoint answers `503` and clients fall back to polling — a refusal, never a connection that hangs |
| `events.poll_seconds` | float | no | `2` | How often a connection looks at the tenant's audit cursor. Lower means a faster page and more queries, one per connected client |
| `events.heartbeat_seconds` | float | no | `20` | A `heartbeat` event is sent after this much silence, so a reverse proxy does not close an idle connection. Keep it below the proxy's read timeout (nginx: 60 s by default) |

### `mcp`

| Key | Type | Required | Default | Notes |
|---|---|---|---|---|
| `mcp.http_enabled` | bool | no | `false` | Mount Streamable HTTP at `/mcp` inside the API process. stdio (`victus mcp --tenant <slug>`) needs no configuration |
| `mcp.allowed_cidrs` | list[str] | no | `["100.64.0.0/10"]` | Source networks allowed to reach `/mcp` (a VPN's CGNAT range by default; set your own). Requests from other addresses get `403` even with a valid token; an empty list `[]` disables the IP filter (token and reverse proxy remain) |
| `mcp.rate_limit_per_minute` | int | no | `120` | Per bearer token |

### `backup`

| Key | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `backup.path` | str | no | `/backups` | Target directory (bind-mount a large disk here) |
| `backup.cron` | str | no | `0 3 * * *` | Daily at 03:00 |
| `backup.retention.daily` | int | no | `7` | Keep last *n* daily |
| `backup.retention.weekly` | int | no | `8` | Keep last *n* weekly |
| `backup.retention.monthly` | int | no | `12` | Keep last *n* monthly |
| `backup.include_sqlite_snapshot` | bool | no | `true` | Add `VACUUM INTO` copy to the archive (SQLite only) |
| `backup.max_age_hours` | int | no | `30` | `/health` turns `backup_age_hours` into a warning beyond this |

### Example `victus.yaml`

```yaml
server:
  base_url: https://victus.example.com
database:
  url: sqlite:////data/victus.db
storage:
  path: /data/blobs
auth:
  rp_id: victus.example.com
  origin: https://victus.example.com
providers:
  openai_api_key: ${VICTUS_PROVIDERS__OPENAI_API_KEY}
  anthropic_api_key: ${VICTUS_PROVIDERS__ANTHROPIC_API_KEY}
agent:
  enabled: true
mcp:
  http_enabled: true
backup:
  path: /backups
```

`${VAR}` references are resolved from the environment at load time; secrets never live in the YAML file itself.

## Tenant settings

Stored as one JSON document per version in `tenant_settings`; every `PUT /settings` creates a new version with
`valid_from`. Reports and the agent read the version valid for the date in question.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `goal.weight_kg` | float | – | Target weight |
| `goal.date` | date | – | Target date (reference stage) |
| `goal.stages[]` | list | `[]` | Named stages `{name, date, note}` for the burndown |
| `kcal_per_kg` | float | `7716.17` | Energy per kg body mass used by TDEE formulas |
| `moving_average_days` | int | `7` | Window for the weight moving average |
| `trend_windows` | list[int] | `[7,14,21,30,60,90]` | Regression windows (days) |
| `tdee_windows` | list[int] | `[3,7,14,21,30,60,90]` | Rolling TDEE windows; very short windows are shown but graded red |
| `calorie_corridor.min` / `.max` | int | `1400` / `2000` | Daily kcal corridor |
| `calorie_corridor.asymmetric` | bool | `true` | Only *above max* is a finding; below min is not |
| `calorie_corridor.rating` | enum | `average` | `average` (over the window) / `per_day` |
| `transcription.language` | str | `en` | Transcription language; the agent also answers in this language |
| `transcription.vocabulary_prompt` | str | `""` | Vocabulary hint passed to the transcription model (product names, brands) so numbers and names come out right |
| `regional.timezone` | str | `Europe/Berlin` | IANA name deciding which calendar day a stored moment counts on |
| `regional.language` | enum | `en` | Interface language: `en`, `de`, `es` or `fr`; separate from the number format |
| `regional.locale` | str | `de-DE` | BCP 47 tag deciding number and date formatting in the interface (`de-DE` writes 1.234,5) |
| `captures.processed_retention_days` | int | `10` | Days a processed capture and its files are kept before both are deleted; `0` keeps them for ever |
| `report_defaults.period` | str | `14d` | Default report window |
| `report_defaults.palette` | object | dataviz default | Series colours for charts |
| `target_bands[]` | reference | – | Managed in table `target_band`, one row per `training_type` and validity range (see below) |

Salt targets are **not** a settings key. They live exclusively in `target_band` ([ADR 0007](adr/0007-single-salt-source.md)).

### Example tenant settings

```yaml
goal:
  weight_kg: 85.0
  date: 2027-03-31
  stages:
    - { name: Stretch, date: 2027-01-31 }
    - { name: Target,  date: 2027-03-31 }
    - { name: Minimum, date: 2027-06-30 }
kcal_per_kg: 7716.17
moving_average_days: 7
trend_windows: [7, 14, 21, 30, 60, 90]
tdee_windows: [3, 7, 14, 21, 30, 60, 90]
calorie_corridor:
  min: 1400
  max: 2000
  asymmetric: true
  rating: average
transcription:
  language: en
  vocabulary_prompt: "quark, skyr, oat milk, whey isolate"
report_defaults:
  period: 14d
```

### Target bands (`target_band`)

One row per training type; `valid_from`/`valid_to` version them. The values below are **example defaults** shipped
in `examples/tenant-settings.yaml`; every tenant sets their own.

| Nutrient | min | optimal | target | max | stretch |
|---|---|---|---|---|---|
| kcal | 1400 | 1400–2000 | – | 2000 | – |
| protein (g) | 105 | 150–185 | 165 | 200 | 185 |
| carbs (g) | 120 | 155–200 | 180 | 230 | – |
| fat (g) | 45 | 55–70 | 58 | 75 | – |
| fiber (g) | 25 | 32–38 | 35 | 50 | 38 |
| salt (g) — `rest` | 4 | 6–8 | 7 | 15 | – |
| salt (g) — `strength` | 4 | 8–10 | 9 | 15 | – |
| salt (g) — `martial_arts` | 4 | 9–10 | 9.5 | 15 | – |

When importing a vault, the importer seeds target bands from the vault's configuration and lists any contradicting
definitions it finds as review items.

## Secrets

| Rule | Detail |
|---|---|
| Never in the repository | `.env` is git-ignored; `deploy/.env.example` documents every variable without values |
| Never in `victus.yaml` | Use `${VAR}` references |
| Rotate on suspicion | API tokens: revoke in the app; provider keys: rotate at the provider, update `.env`, `docker compose up -d` |
| Scanned in CI | Trivy secret scanner runs on every push |
