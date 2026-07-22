# Coreflow — developer entry point.
#
#   make setup   first-time setup (creates .env, builds, migrates, seeds demo data)
#   make up      start the stack
#   make help    list every target

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
BACKEND := $(COMPOSE) exec -T backend
BACKEND_RUN := $(COMPOSE) run --rm -T backend
FRONTEND := $(COMPOSE) exec -T frontend

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
.PHONY: setup
setup: .env build up-wait migrate seed ## First-time setup: everything, one command
	@echo ""
	@echo "  Coreflow is ready."
	@echo ""
	@echo "  Frontend    http://localhost:3000"
	@echo "  API docs    http://localhost:8000/api/docs/"
	@echo "  Mailpit     http://localhost:8025"
	@echo "  MinIO       http://localhost:9001"
	@echo ""
	@echo "  Log in with the demo credentials printed by 'make seed' above."
	@echo ""

.env: ## Create .env from the example if absent
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env from .env.example."; \
		echo "Integrations are disabled by default — the stack runs on demo data."; \
	else \
		echo ".env already exists; leaving it alone."; \
	fi

# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------
.PHONY: build
build: ## Build all images
	$(COMPOSE) build

.PHONY: up
up: .env ## Start the stack (detached)
	$(COMPOSE) up -d

.PHONY: up-wait
up-wait: .env ## Start the stack and wait for healthchecks
	$(COMPOSE) up -d --wait

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop and DELETE all volumes (destroys local data)
	$(COMPOSE) down -v --remove-orphans

.PHONY: restart
restart: down up ## Restart the stack

.PHONY: logs
logs: ## Follow all logs
	$(COMPOSE) logs -f

.PHONY: logs-backend
logs-backend: ## Follow backend logs
	$(COMPOSE) logs -f backend

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: shell
shell: ## Django shell
	$(COMPOSE) exec backend python manage.py shell

.PHONY: bash
bash: ## Shell inside the backend container
	$(COMPOSE) exec backend bash

.PHONY: psql
psql: ## Postgres shell
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-coreflow} -d $${POSTGRES_DB:-coreflow}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply migrations
	$(BACKEND) python manage.py migrate --noinput

.PHONY: migrations
migrations: ## Generate migrations
	$(BACKEND) python manage.py makemigrations

.PHONY: migrations-check
migrations-check: ## Fail if a model change has no migration
	$(BACKEND) python manage.py makemigrations --check --dry-run

.PHONY: seed
seed: ## Load demo data (idempotent)
	$(BACKEND) python manage.py seed_demo

.PHONY: seed-reset
seed-reset: ## Wipe and reload demo data
	$(BACKEND) python manage.py seed_demo --reset

.PHONY: frontend-clean
frontend-clean: ## Fix stale UI after updates: wipe the cached Next.js build and restart
	$(COMPOSE) rm -sf frontend
	-docker volume rm coreflow_frontend-next
	$(COMPOSE) up -d frontend

.PHONY: frontend-prod
frontend-prod: ## Snappy UI for daily use: build & run the production frontend (no live reload)
	$(COMPOSE) rm -sf frontend
	$(COMPOSE) --profile prod up -d --build frontend-prod

.PHONY: frontend-dev
frontend-dev: ## Back to the live-reload dev frontend
	-$(COMPOSE) --profile prod rm -sf frontend-prod
	$(COMPOSE) up -d frontend

.PHONY: bootstrap
bootstrap: ## Productive user+workspace, NO demo data: make bootstrap EMAIL=you@x.de NAME="Meine Firma"
	$(if $(strip $(EMAIL)),,$(error EMAIL is required. Usage: make bootstrap EMAIL=you@x.de NAME="Meine Firma" [PASSWORD=...] [SMALL_BUSINESS=1]))
	$(if $(strip $(NAME)),,$(error NAME is required. Usage: make bootstrap EMAIL=you@x.de NAME="Meine Firma" [PASSWORD=...] [SMALL_BUSINESS=1]))
	$(BACKEND) python manage.py bootstrap --email "$(EMAIL)" --workspace-name "$(NAME)" $(if $(strip $(PASSWORD)),--password "$(PASSWORD)") $(if $(strip $(SMALL_BUSINESS)),--small-business)

.PHONY: superuser
superuser: ## Create a Django superuser
	$(COMPOSE) exec backend python manage.py createsuperuser

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
.PHONY: test
test: test-backend test-frontend ## Run backend + frontend unit tests

.PHONY: test-backend
test-backend: ## Backend tests (pytest)
	$(BACKEND) pytest

.PHONY: test-backend-cov
test-backend-cov: ## Backend tests with coverage
	$(BACKEND) pytest --cov=apps --cov-report=term-missing --cov-report=html

.PHONY: test-frontend
test-frontend: ## Frontend unit tests (vitest)
	$(FRONTEND) npm run test:run

.PHONY: test-e2e
test-e2e: ## End-to-end journey: client -> time -> invoice -> Lexware -> paid (mocked providers)
	$(BACKEND) pytest apps/invoicing/tests/test_journey.py -v

.PHONY: lint
lint: lint-backend lint-frontend ## Lint everything

.PHONY: lint-backend
lint-backend: ## Ruff
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .

.PHONY: lint-frontend
lint-frontend: ## ESLint
	$(FRONTEND) npm run lint

.PHONY: format
format: ## Auto-format everything
	$(BACKEND) ruff check --fix .
	$(BACKEND) ruff format .
	$(FRONTEND) npm run format

.PHONY: typecheck
typecheck: typecheck-backend typecheck-frontend ## Type-check everything

.PHONY: typecheck-backend
typecheck-backend: ## mypy
	$(BACKEND) mypy .

.PHONY: typecheck-frontend
typecheck-frontend: ## tsc --noEmit
	$(FRONTEND) npm run typecheck

.PHONY: check
check: lint typecheck migrations-check test ## Everything CI runs

# ---------------------------------------------------------------------------
# API schema
# ---------------------------------------------------------------------------
.PHONY: schema
schema: ## Write the OpenAPI schema to docs/api/openapi.yaml
	$(BACKEND) python manage.py spectacular --file /app/../docs/api/openapi.yaml --validate

# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------
.PHONY: sync-lexware
sync-lexware: ## Trigger a full Lexware sync
	$(BACKEND) python manage.py sync_provider lexware --full

.PHONY: sync-clockify
sync-clockify: ## Trigger a full Clockify sync
	$(BACKEND) python manage.py sync_provider clockify --full

.PHONY: test-connection
test-connection: ## Test configured provider connections
	$(BACKEND) python manage.py test_provider_connection

# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------
.PHONY: backup
backup: ## Dump the database to backups/
	@mkdir -p backups
	$(COMPOSE) exec -T postgres pg_dump -U $${POSTGRES_USER:-coreflow} -d $${POSTGRES_DB:-coreflow} -F c \
		> backups/coreflow-$$(date +%Y%m%d-%H%M%S).dump
	@echo "Wrote backups/coreflow-$$(date +%Y%m%d-%H%M%S).dump"

.PHONY: restore
restore: ## Restore from a dump: make restore FILE=backups/xxx.dump
	$(if $(strip $(FILE)),,$(error FILE is required. Usage: make restore FILE=backups/xxx.dump))
	$(COMPOSE) exec -T postgres pg_restore -U $${POSTGRES_USER:-coreflow} -d $${POSTGRES_DB:-coreflow} \
		--clean --if-exists < $(FILE)
	@echo "Restored from $(FILE)"
