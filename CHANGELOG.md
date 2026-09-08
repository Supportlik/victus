# Changelog

All notable changes to Victus are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Stage 0 scaffold: Python package (`victus` CLI, FastAPI factory, `/api/v1/health` and `/api/v1/version`),
  configuration loader (env > `victus.yaml` > defaults), Angular workspace under `web/`.
- Specification, architecture, configuration, API, reports, agent, MCP, deployment, migration,
  backup, operations and test-plan documents under `docs/`, plus ADRs 0001–0008.
- JSON Schemas for server config, tenant settings, report definitions, backup manifests and agent drafts.
- Docker Compose stack (`deploy/`) with api, web, worker, backup services and optional postgres/caddy profiles.
- CI (pytest 3.12–3.14 × SQLite/PostgreSQL, ruff, mypy), web, security, docker and release workflows.

[Unreleased]: https://github.com/Supportlik/victus/compare/main...HEAD
