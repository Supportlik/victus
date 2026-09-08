# Victus

[![CI](https://github.com/Supportlik/victus/actions/workflows/ci.yml/badge.svg)](https://github.com/Supportlik/victus/actions/workflows/ci.yml)
[![Web](https://github.com/Supportlik/victus/actions/workflows/web.yml/badge.svg)](https://github.com/Supportlik/victus/actions/workflows/web.yml)
[![Security](https://github.com/Supportlik/victus/actions/workflows/security.yml/badge.svg)](https://github.com/Supportlik/victus/actions/workflows/security.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Self-hosted nutrition tracking with a real API.** Victus keeps your food diary, product
database, recipes, weight history and target bands in one database, exposes everything over
REST and MCP, renders dashboards and "am I on track?" check-ups, and lets an AI agent turn
voice notes, photos and free text into day-log drafts you approve with one command.

> **Victus** (Latin *vīctus*: "nourishment, means of living, way of life").

> **Status: pre-release (Stages 1 and 2 implemented, Stage 3 — captures, agent, MCP — pending).**
> Database, REST API with passkeys and tokens, Angular web app, report engine with the built-in
> check-up, and backup/restore are in place. See [`docs/PLAN.md`](docs/PLAN.md) for the roadmap.

## How it works

```
 phone / browser ──► Angular web app (passkey login) ──┐
 voice · photo · text ──► captures ──► agent (Claude) ──┤──► REST API ──► use cases ──► SQLite / PostgreSQL
 Claude Code · claude.ai ──► MCP (stdio | streamable HTTP) ──┘        │
                                                                        └──► reports: JSON · Markdown · SVG
```

* **One database, one truth.** Nutrients are never stored on a meal line; they are computed from
  the product the line points to, so a corrected label fixes every historical day. Quantities,
  on the other hand, are frozen when you log them (ADR 0001, `docs/SPEC.md` R1–R4).
* **Drafts, then approval.** The agent proposes; you approve — in the web app or by answering a
  summary in your Claude chat. Estimated items stay marked as estimates after approval.
* **Reports as data.** Dashboards and check-ups are declarative YAML documents rendered to JSON
  (web), Markdown (chat, Obsidian) or SVG.
* **Multi-tenant, token-authenticated, backed up.** Every row belongs to a tenant; passkeys for
  people, scoped bearer tokens for scripts and agents; backups are plain JSONL you can read.

## Installation

Victus ships as a Docker Compose stack (`deploy/`). Requirements: Docker with Compose v2, an
HTTPS-terminating reverse proxy (Caddy configuration included), and a fixed hostname for WebAuthn.

```bash
git clone https://github.com/Supportlik/victus.git
cd victus
cp deploy/.env.example deploy/.env      # set VICTUS_AUTH__RP_ID and VICTUS_AUTH__ORIGIN first!
docker compose -f deploy/docker-compose.yml up -d
curl -s http://127.0.0.1:8090/api/v1/health
```

For a plain Python install (development, CLI only):

```bash
uv tool install "victus[all]"     # or: pip install "victus[all]"
victus --version
victus serve --port 8000
```

## Quick start

```bash
victus serve                                  # API + web app + MCP endpoint
victus backup restore victus-alice-20260908.zip   # bring existing data in via the archive format (docs/MIGRATION.md)
victus backup create --all                    # write a verifiable backup archive
victus mcp --tenant alice                     # MCP over stdio for Claude Code (Stage 3)
victus agent run --mode historical            # process open captures into drafts (Stage 3)
```

## Configuration

Two layers, documented in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md):

| Layer | Where | Examples |
|---|---|---|
| Server config | `victus.yaml` + `VICTUS_*` environment | database URL, storage path, `rp_id`, provider keys, agent budget, backup schedule |
| Tenant settings | versioned per tenant in the database | goal weight and date, calorie corridor, target bands per training day, Whisper vocabulary |

JSON Schemas for both live in [`schemas/`](schemas/); [`examples/`](examples/) holds complete,
validated examples.

## Documentation

| Document | Content |
|---|---|
| [`docs/SPEC.md`](docs/SPEC.md) | Requirements R1…Rn and design decisions D1…Dn |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Hexagonal layers, package layout, sequence diagrams |
| [`docs/API.md`](docs/API.md) · [`docs/MCP.md`](docs/MCP.md) | REST resources, MCP tools and scopes |
| [`docs/REPORTS.md`](docs/REPORTS.md) · [`docs/AGENT.md`](docs/AGENT.md) | Report definitions; agent runs, runners, approval |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) · [`docs/MIGRATION.md`](docs/MIGRATION.md) | Compose stack, passkey prerequisites; vault import |
| [`docs/BACKUP.md`](docs/BACKUP.md) · [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Backup format and restore runbook; incident runbook |
| [`docs/TESTPLAN.md`](docs/TESTPLAN.md) | Complete test plan with case IDs and reference values |
| [`docs/adr/`](docs/adr/) | Architecture decision records |

## Development

```bash
uv sync --all-extras --dev          # Python
uv run pytest -q                    # tests (see docs/TESTPLAN.md for markers)
uv run ruff check . && uv run ruff format --check .
uv run mypy src
cd web && npm ci && npm test && npm run build   # Angular
make help                           # docker compose wrappers (up, logs, backup, restore, …)
```

Every push runs the suite on Python 3.12–3.14 against SQLite and PostgreSQL, builds the web app,
scans dependencies and sources (pip-audit, npm audit, Trivy, CodeQL) and builds the container images.

## License

[MIT](LICENSE) — © 2026 Michael Bortlik
