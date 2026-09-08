# Victus — developer and operator shortcuts.
# Thin wrappers around uv, npm and docker compose. Recipes use tabs.

COMPOSE      ?= docker compose -f deploy/docker-compose.yml
COMPOSE_ENV  ?= $(if $(wildcard deploy/.env),--env-file deploy/.env,)
COMPOSE_CMD   = $(COMPOSE) $(COMPOSE_ENV)
TENANT       ?= demo

.DEFAULT_GOAL := help
.PHONY: help install lint format test test-all privacy web-build web-start up down logs ps pull backup verify restore shell mcp

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target>\n\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

# ── Development ─────────────────────────────────────────────────────────────
install: ## Install Python (uv) and web (npm) dependencies
	uv sync --all-extras --dev
	cd web && npm ci --no-audit --no-fund

lint: ## ruff check + ruff format --check + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src

format: ## Auto-format with ruff
	uv run ruff format .
	uv run ruff check --fix .

test: ## pytest against in-memory SQLite
	uv run pytest -q

test-all: ## pytest against SQLite and PostgreSQL (starts the postgres profile)
	uv run pytest -q
	$(COMPOSE_CMD) --profile postgres up -d postgres
	VICTUS_TEST_DATABASE_URL=postgresql+psycopg://victus:$${POSTGRES_PASSWORD:-victus}@localhost:5432/victus uv run pytest -q
	$(COMPOSE_CMD) --profile postgres stop postgres

web-build: ## Angular production build
	cd web && npm run build -- --configuration production

web-start: ## Angular dev server (http://localhost:4200)
	cd web && npm start

# ── Stack ───────────────────────────────────────────────────────────────────
up: ## Start the stack (api, web, worker, backup)
	$(COMPOSE_CMD) up -d

down: ## Stop the stack
	$(COMPOSE_CMD) down

logs: ## Follow api + worker logs
	$(COMPOSE_CMD) logs -f api worker

ps: ## Show service status and health
	$(COMPOSE_CMD) ps

pull: ## Pull the latest images and restart
	$(COMPOSE_CMD) pull
	$(COMPOSE_CMD) up -d

# ── Backup ──────────────────────────────────────────────────────────────────
backup: ## Create a backup of all tenants (deploy/backup/backup.sh)
	sh deploy/backup/backup.sh --all

verify: ## Verify the newest backup archive
	sh deploy/backup/verify.sh --latest

restore: ## Restore an archive: make restore ARCHIVE=victus-<tenant>-<timestamp>.zip
	@test -n "$(ARCHIVE)" || { echo "usage: make restore ARCHIVE=<file.zip> [DRY=1]"; exit 1; }
	sh deploy/backup/restore.sh "$(ARCHIVE)" $(if $(DRY),--dry-run,)

# ── Operations ──────────────────────────────────────────────────────────────
shell: ## Interactive shell in the api container
	$(COMPOSE_CMD) exec api sh

mcp: ## Run the stdio MCP server against the running stack (TENANT=demo)
	$(COMPOSE_CMD) run --rm -T --no-deps api mcp --tenant $(TENANT)

privacy: ## Fail on personal data in the tree (set VICTUS_PRIVACY_DENYLIST for the private term list)
	uv run python scripts/privacy_check.py
