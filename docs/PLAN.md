# Roadmap

Victus is built in stages. Each stage has a definition of done that is checked, not felt. Detailed planning
(decisions, rationale, verification) lives in the author's private planning notes; this page is the public summary
and is updated per stage.

## Status

| Stage | State | Date |
|---|---|---|
| 0 — Scaffold | **in progress** | 08 Sep 2026 |
| 1 — Core | planned | |
| 2 — Reports | planned | |
| 3 — Agent | planned | |
| Cross-cutting / v0.1.0 | planned | |

## Stages

### Stage 0 — Scaffold

| Content | Definition of done | Risks |
|---|---|---|
| Repository, `uv` + hatchling packaging, package skeleton, Angular skeleton, CI/security/web/docker/release workflows, README, `docs/` incl. SPEC/TESTPLAN/BACKUP/OPERATIONS, ADRs 0001–0008, empty JSON schemas, MIT licence, CHANGELOG, `deploy/` with the full Compose stack and backup wrappers | CI green; `victus --version`; `ng build` passes | — |

### Stage 1 — Core

| Content | Definition of done | Risks |
|---|---|---|
| Domain model + views, Alembic `0001_initial` (schema + tenancy, drafts, captures, agent tables), repositories, CRUD use cases, vault importer with round-trip gate and review list, WebAuthn + sessions + API tokens, REST, Angular (login, day log, products/search, review list, manual weight, tokens), scale-sync adapter, backup create/verify, first deployment, `RP_ID` pinned | Import report ≥ the dry-run baseline; one day logged in the web app; two passkeys registered; backup created and verified | `RP_ID` before the first passkey; primary-key change of `day_log`; matcher quality (the review list is a UI, not a blocker) |

### Stage 2 — Reports

| Content | Definition of done | Risks |
|---|---|---|
| Report engine and blocks, `checkup.yaml`, JSON/Markdown renderers, Angular dashboard (ECharts), **TDEE reference tests** against frozen predecessor output, scheduler for scale sync, optional SVG/Markdown export to the vault | Check-up Markdown matches the predecessor's status output and dashboard pages; fixture tests green | Deviations between reference and new code are documented, not "fixed" in the fixture |

### Stage 3 — Agent

| Content | Definition of done | Risks |
|---|---|---|
| Captures, attachments, transcription port + OpenAI adapter, MCP server (stdio + Streamable HTTP), `agent_lock`, in-house worker (Claude Agent SDK), prompt files, drafts UI + approval, cost protocol, external runner via Claude Code `/schedule`, chat summary | Voice note from the phone → draft → chat summary → `day_approve`, without any vault script; both runners tested; no double draft | Image analysis cost (budget), transcription quality (vocabulary prompt), HTTP MCP reachable from the VPN only |

### Cross-cutting

| Content | Definition of done |
|---|---|
| Multi-tenant isolation tests, backup schedule + restore drill, complete documentation, `CHANGELOG.md`, release **v0.1.0**; predecessor tooling marked "replaced by Victus" (nothing deleted) | A second test tenant is fully isolated; restore into a temporary database verified; SPEC requirements all point at implemented modules |

## Principles that do not change between stages

- The database is the only source of truth; Markdown is an export.
- Nutrients are computed, never stored per item.
- The agent drafts; a human approves.
- No personal or health data in the repository — examples and fixtures are synthetic.
- Every stage ends with tests and a runbook update, not with "it works on my machine".
