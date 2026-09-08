# Changelog

All notable changes to Victus are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Stage 1: persistence layer (29 tables, 5 nutrient views, Alembic migration with unit seed, tenant-scoped
  repositories), use cases, REST API under `/api/v1` (products, portions, recipes, batches, days, meals,
  line items, drafts and approval, weight, settings, target bands, day threads), WebAuthn passkeys with
  recovery codes, server-side sessions with CSRF, scoped API tokens, admin CLI (`migrate`, `tenant`,
  `user`, `token`, `passkey`), backup create/verify/restore/prune/schedule with JSONL archives.
- Stage 2: pure reporting domain (TDEE weekly and rolling, moving average, trend, forecast, burndown, band
  rating, reliability grade, day consistency checks) pinned to synthetic reference values; declarative
  report engine with nine block types, JSON and Markdown renderers, built-in `checkup`, `/reports` API.
- Angular web app: passkey login and recovery, days and day view with band gauges and day thread, drafts
  approval, products with review list, recipes, weight, captures with "Process now", settings (target
  bands, tokens, passkeys), reports dashboard with one component per block type.
- Domain services for product matching (three-tier), quantity parsing and the unit table; privacy check
  script and CI job (SPEC R48).
- Stage 3: captures (text, audio, image) with content-hash dedupe, attachments in blob storage, transcription
  port with the OpenAI `gpt-4o-transcribe` adapter (ffmpeg conversion, tenant vocabulary prompt); agent use
  cases (queue/begin/finish runs, per-day locks, day context, schema-validated `CreateDraft`, sessions); the
  in-house runner (Anthropic SDK tool loop, one model session per day, budget, pricing, prompt files with
  version hash) and the worker (queue consumer for **Process now**, optional cron, heartbeat); one tool
  registry serving the MCP server (stdio `victus mcp --tenant`, Streamable HTTP at `/mcp` with bearer scopes,
  CIDR allow-list and rate limit) and the runner; REST `/captures`, `/attachments/{id}`, `/agent/runs`,
  `/agent/locks`; CLI `victus agent run|runs|unlock`, `victus worker [--once]`, `victus mcp`; web: captures
  page with transcripts, media, set-day/discard/re-transcribe, Agent page with runs, sessions, summaries,
  cancel and force-unlock, day thread states.

### Changed
- No importer in the product (ADR 0011): existing data enters through the backup archive format, REST or MCP.
- One model session per day (ADR 0009) and a resumable per-day thread (ADR 0010); lock TTL 5 minutes;
  agent runs start on demand (`POST /agent/runs`), cron optional.
- Alpine base images pinned to the newest tags; GitHub Actions at current majors.
- Agent default model `claude-opus-5` with adaptive thinking (`agent.effort`, default `medium`); server-side
  refusal fallbacks on by default (`agent.fallbacks`); budget defaults 400k/40k tokens, 2 USD, 12 images per run;
  new keys `agent.poll_seconds`, `agent.max_tokens`, `agent.max_turns_per_day`, `agent.pricing`.
- The worker is a queue consumer: `POST /agent/runs` is processed within `agent.poll_seconds`; `agent.enabled`
  only controls the cron schedule.

### Stage 0
- Stage 0 scaffold: Python package (`victus` CLI, FastAPI factory, `/api/v1/health` and `/api/v1/version`),
  configuration loader (env > `victus.yaml` > defaults), Angular workspace under `web/`.
- Specification, architecture, configuration, API, reports, agent, MCP, deployment, migration,
  backup, operations and test-plan documents under `docs/`, plus ADRs 0001–0008.
- JSON Schemas for server config, tenant settings, report definitions, backup manifests and agent drafts.
- Docker Compose stack (`deploy/`) with api, web, worker, backup services and optional postgres/caddy profiles.
- CI (pytest 3.12–3.14 × SQLite/PostgreSQL, ruff, mypy), web, security, docker and release workflows.

[Unreleased]: https://github.com/Supportlik/victus/compare/main...HEAD
