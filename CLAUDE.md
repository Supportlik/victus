# Victus — working rules for Claude Code

Read `docs/PLAN.md` (roadmap and stage status) and `docs/SPEC.md` before changing anything.

## Language and privacy

- **Everything in this repository is English**: code identifiers, comments, docs, commit messages,
  schema keys, CLI options, MCP tool names. Domain names are English too (`day_log`, `line_item`,
  `target_band` — see `docs/GLOSSARY.md`). German appears only where the vault importer parses
  German source Markdown.
- **No personal data, ever.** No real body metrics, goal dates, hostnames, IPs, tenant names or
  vocabulary of the author or any user in code, docs, examples, fixtures or commit messages. Use
  `victus.example.com`, tenant `alice`, illustrative numbers. Test fixtures are synthetic or
  anonymised. Runtime data lives outside the repo (`data/`, `backups/`, `.env` are git-ignored).
- Conversation with the author may be in German; artefacts stay English.

## Architecture rules (see docs/ARCHITECTURE.md)

- Hexagonal layers: `domain` → `application` → `infrastructure` / `api` / `mcp` / `cli` / `agent`.
- `victus.domain` imports nothing from other layers and no framework (enforced by
  `tests/unit/domain/test_purity.py`). Time is passed in, never read from the clock there.
- Every primary adapter calls a use case; a use case is one transaction and takes a `TenantContext`.
- Nutrients are computed, never stored on line items. Quantities are frozen at logging time.
- Only dialect-neutral SQLAlchemy; every schema change is an Alembic migration; SQLite and
  PostgreSQL both run in CI.
- `belastbar`/`offen` semantics from the source vault map to `day_log.reliable` and
  `day_log.status` (`draft` | `open` | `closed`); there are no defaults — a missing value is an error.

## Working conventions

- Tests first for domain services; reference values for TDEE/trend/forecast live in
  `tests/fixtures/tdee_reference.json` and are never "adjusted to pass" — a mismatch is a finding.
- Every test case has an ID from `docs/TESTPLAN.md` in its docstring; new behaviour adds a row there.
- **A green suite is not a check.** Whatever area was touched is opened in a browser and looked at
  afterwards — the fault that a test with a wrong fixture hides, or that only exists in a real
  recording, is found there and nowhere else. See "Look at what you changed" in `docs/TESTPLAN.md`.
- Releases follow the versioning rules and the release checklist in `CONTRIBUTING.md`: what each
  part of the number covers, which part an issue raises, and the steps every release runs through
  in order — including the run against PostgreSQL, which is where dialect-specific migration
  faults appear and SQLite stays silent.
- Update the matching document in `docs/` in the same change (SPEC requirement table,
  CONFIGURATION keys, API resources, TESTPLAN rows, CHANGELOG "Unreleased").
- Commands: `uv sync --all-extras --dev`, `uv run pytest -q`, `uv run ruff check . && uv run ruff format --check .`,
  `uv run mypy src`, `cd web && npm test -- --watch=false && npm run build`, `make help`.
- Do not commit or push unless the author asks. Conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`).
- Placeholder CLI commands exit with code 3 and name the stage that delivers them; keep that honest.

## Versions and base images

- Always use the **newest stable, compatible** versions: Python packages resolve to latest (`uv lock --upgrade`),
  npm packages to latest within Angular's supported ranges (`npm outdated`), GitHub Actions at their latest
  major, base images at their newest tag.
- Docker base images are **Alpine** variants, pinned to an explicit newest tag (e.g. `python:3.14.x-alpine3.2x`,
  `node:26.x-alpine3.2x`, `nginx-unprivileged:mainline-alpine3.2x`, `postgres:18.x-alpine3.2x`,
  `caddy:2.x-alpine`). Dependabot proposes bumps; accept them unless a test fails.
- Exception only for genuine incompatibility (e.g. TypeScript stays within the range the Angular compiler
  supports); document the reason next to the pin.
