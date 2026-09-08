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

### Changed
- No importer in the product (ADR 0011): existing data enters through the backup archive format, REST or MCP.
- One model session per day (ADR 0009) and a resumable per-day thread (ADR 0010); lock TTL 5 minutes;
  agent runs start on demand (`POST /agent/runs`), cron optional.
- Alpine base images pinned to the newest tags; GitHub Actions at current majors.

### Stage 0
- Stage 0 scaffold: Python package (`victus` CLI, FastAPI factory, `/api/v1/health` and `/api/v1/version`),
  configuration loader (env > `victus.yaml` > defaults), Angular workspace under `web/`.
- Specification, architecture, configuration, API, reports, agent, MCP, deployment, migration,
  backup, operations and test-plan documents under `docs/`, plus ADRs 0001–0008.
- JSON Schemas for server config, tenant settings, report definitions, backup manifests and agent drafts.
- Docker Compose stack (`deploy/`) with api, web, worker, backup services and optional postgres/caddy profiles.
- CI (pytest 3.12–3.14 × SQLite/PostgreSQL, ruff, mypy), web, security, docker and release workflows.

[Unreleased]: https://github.com/Supportlik/victus/compare/main...HEAD
